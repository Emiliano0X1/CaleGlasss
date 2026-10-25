/**
 * Reporter agent: prompt and tools. It reads Jira and Confluence and proposes a report page;
 * it never publishes anything itself.
 *
 * Read-only tools: search_issues(jql), sprints() (closed ones too), search_pages(cql),
 * read_page(id).
 * The last tool, propose(summary, space, parent_id, title, content), validates the page,
 * saves a plan with one action, publish_page, as pending in stdb (submit_proposal) and sends
 * it to Telegram (title, where it goes, its sections and the summary) with a ✅ Approve button,
 * like the Jira agent. execute/actions.ts creates the page after approval.
 *
 * Reports go under the page PARENT_TITLE in the space REPORT_SPACE. Format: the team note
 * reporter/report-format if there is one (agents/memory.ts), else the example report there;
 * when the team asks for a new format, the agent saves it with save_note.
 *
 * propose rejects the page (is_error, so Claude fixes it) if the space or the parent page
 * doesn't exist (or the parent is in another space), the title is empty or already taken
 * in that space, or the content is empty or too long.
 */
import { type AgentSpec, type AgentTool, ToolError } from './loop';
import { proposalId } from './jira_agent';
import { getPage, getSpace, pageByTitle, searchPages } from '../lib/confluence';
import { BOARD_ID, PROJECT_KEY, searchIssues, sprints } from '../lib/jira';
import { call } from '../lib/stdb';
import { send } from '../lib/telegram';

export const REPORTER_NAME = 'reporter';
export const REPORT_SPACE = 'Team';
export const PARENT_TITLE = 'Sprint reports';

export interface PublishPageAction {
  type: 'publish_page';
  space: string;        // space key
  parent_id: string;
  title: string;
  content: string;      // Confluence storage format (XHTML)
}

export interface ReporterContext {
  workId: string;
  requestText: string;
  chatId: string | null;
}

const MAX_CONTENT = 60_000;
const MAX_PAGE_CHARS = 20_000;   // read_page returns at most this much body, to keep the context short

const SYSTEM = `You are the reporter agent of a team assistant. Someone asked by voice from their smart glasses for a report (a sprint report, the status of some work, someone's pending issues). Your job is to gather the data and propose a Confluence page for a human to approve.

Context:
- Jira project key: ${PROJECT_KEY}. Scrum board id: ${BOARD_ID}. sprints() lists its sprints, closed ones included; use the sprint id in JQL (sprint = <id>).
- The Jira site is in Spanish: issue types and statuses come in Spanish (Error = bug, Historia = story, Tarea = task; "Por hacer", "En curso", "Listo"). Use status_category ("new", "indeterminate", "done") to know whether an issue is finished.
- JQL needs English issue type names (issuetype = Bug, Story, Task) and statusCategory instead of status names. Always include project = ${PROJECT_KEY}.
- Reports go in the Confluence space "${REPORT_SPACE}", under the page "${PARENT_TITLE}". Find that page with search_pages (title = "${PARENT_TITLE}"); its result gives you its id (parent_id) and the space key.
- Report format: if the team notes have one (reporter/report-format), use exactly those sections, in that order; it wins over the example page. Otherwise, under the parent there's an example report: find it with search_pages (ancestor = <parent id>), read it with read_page and follow its structure, sections, tone and language. If there's neither, use: summary, done, not finished, blockers / risks, numbers (issues done vs total), in the language of the request.
- If the request asks for different sections or says the team's format changed, use the new format AND save it with save_note (path reporter/report-format, the sections in order), so the next reports use it without being asked.

Rules:
- You NEVER publish. You only read with the tools and, at the end, call propose once. A person approves it later.
- Only report what the tools returned: every issue key, name, status and number in the page must come from a tool result. Never invent data.
- If what was asked doesn't exist or is ambiguous (for example, no sprint with that number), don't propose: answer in one or two short sentences saying what's missing.
- Title: follow the example's pattern (e.g. "Sprint 12 Report"); it must not be the title of an existing page in the space.
- content is Confluence storage format (XHTML): <h2>, <p>, <ul><li>, <table><tbody><tr><th>/<td>, <strong>. Close every tag and escape & < > in text. Mention issues as plain text (e.g. ${PROJECT_KEY}-8: summary).
- If propose returns an error, fix the page and call propose again.
- summary is one sentence in the language of the request saying what the report covers.`;

export function createReporterAgent(ctx: ReporterContext): AgentSpec {
  const tools: AgentTool[] = [
    {
      definition: {
        name: 'search_issues',
        description: 'Search Jira issues with JQL. Returns up to 100 issues with key, summary, type, status, status_category, priority and assignee.',
        input_schema: {
          type: 'object',
          properties: { jql: { type: 'string', description: 'JQL query, e.g. "project = PROJ AND sprint = 5207"' } },
          required: ['jql'],
          additionalProperties: false,
        },
      },
      run: async ({ jql }) => {
        const issues = await searchIssues(String(jql), 100);
        console.log(`reporter: search_issues "${jql}" -> ${issues.length} issues`);
        return { content: issues };
      },
    },
    {
      definition: {
        name: 'sprints',
        description: `All sprints of board ${BOARD_ID} (closed, active and future): id, name and state.`,
        input_schema: { type: 'object', properties: {}, additionalProperties: false },
      },
      run: async () => ({ content: await sprints(BOARD_ID, 'closed,active,future') }),
    },
    {
      definition: {
        name: 'search_pages',
        description: 'Search Confluence pages with CQL. Returns id, title, space_key and an excerpt of each page.',
        input_schema: {
          type: 'object',
          properties: { cql: { type: 'string', description: `CQL, e.g. title = "${PARENT_TITLE}" or ancestor = 12345` } },
          required: ['cql'],
          additionalProperties: false,
        },
      },
      run: async ({ cql }) => {
        const pages = await searchPages(String(cql));
        console.log(`reporter: search_pages "${cql}" -> ${pages.length} pages`);
        return { content: pages };
      },
    },
    {
      definition: {
        name: 'read_page',
        description: 'Read one Confluence page by id: title, space_id, parent_id and its body in storage format.',
        input_schema: {
          type: 'object',
          properties: { id: { type: 'string', description: 'Page id from search_pages' } },
          required: ['id'],
          additionalProperties: false,
        },
      },
      run: async ({ id }) => {
        const page = await getPage(pageId(id));
        return { content: { ...page, body: page.body.slice(0, MAX_PAGE_CHARS) } };
      },
    },
    {
      definition: {
        name: 'propose',
        description:
          'Submit the report page for human approval. Nothing is published. Returns an error listing what to fix if the page is invalid.',
        input_schema: {
          type: 'object',
          properties: {
            summary: { type: 'string', description: 'One sentence describing the report' },
            space: { type: 'string', description: 'Space key, from search_pages' },
            parent_id: { type: 'string', description: `Id of the page "${PARENT_TITLE}"` },
            title: { type: 'string', description: 'Title of the new page' },
            content: { type: 'string', description: 'Page body in Confluence storage format (XHTML)' },
          },
          required: ['summary', 'space', 'parent_id', 'title', 'content'],
          additionalProperties: false,
        },
      },
      run: (input) => propose(ctx, input),
    },
  ];

  return { name: REPORTER_NAME, system: SYSTEM, tools };
}

async function propose(ctx: ReporterContext, input: Record<string, unknown>): Promise<{ content: unknown; done: boolean }> {
  const text = (key: string) => (typeof input[key] === 'string' ? (input[key] as string).trim() : '');
  const [summary, spaceKey, parentId, title, content] = ['summary', 'space', 'parent_id', 'title', 'content'].map(text);
  const problems: string[] = [];
  if (!summary) problems.push('summary is empty');
  if (!title || title.length > 255) problems.push('title must be 1-255 characters');
  if (!content) problems.push('content is empty');
  if (content.length > MAX_CONTENT) problems.push(`content is too long (${content.length} characters, at most ${MAX_CONTENT})`);
  if (/<script/i.test(content)) problems.push('content must not contain <script>');

  const space = spaceKey ? await getSpace(spaceKey) : null;
  if (!space) problems.push(`space "${spaceKey}" doesn't exist`);
  let parentTitle = '';
  if (!/^\d+$/.test(parentId)) {
    problems.push(`parent_id "${parentId}" is not a page id`);
  } else if (space) {
    const parent = await getPage(parentId).catch(() => null);
    if (!parent) problems.push(`parent page ${parentId} doesn't exist`);
    else if (parent.space_id !== space.id) problems.push(`parent page ${parentId} is not in space ${space.key}`);
    else parentTitle = parent.title;
  }
  if (space && title && (await pageByTitle(space.id, title))) {
    problems.push(`a page titled "${title}" already exists in ${space.key}; use another title`);
  }

  if (problems.length > 0) {
    console.log(`reporter: page rejected: ${problems.join('; ')}`);
    throw new ToolError(`The page was rejected, fix these and call propose again:\n- ${problems.join('\n- ')}`);
  }

  const action: PublishPageAction = { type: 'publish_page', space: space!.key, parent_id: parentId, title, content };
  const id = proposalId(ctx.workId);
  await call('submit_proposal', [id, ctx.workId, REPORTER_NAME, summary, JSON.stringify([action])]);
  console.log(`reporter: proposal ${id} saved, page "${title}" (${content.length} characters)`);

  if (ctx.chatId) {
    const sections = headings(content);
    const list = sections.length ? `\n\nSections:\n${sections.map((s) => `• ${s}`).join('\n')}` : '';
    const message =
      `📝 Report for "${ctx.requestText}"\n${summary}\n\n📄 ${title}\nIn: ${space!.name} › ${parentTitle}${list}`.slice(0, 4000);
    const messageId = await send(ctx.chatId, message, [[{ text: '✅ Approve', data: `ap:${id}` }]]);
    await call('save_plan_message', [id, ctx.chatId, messageId, message]);
  }
  return { content: { ok: true, proposal_id: id, title }, done: true };
}

/** Text of the <h1>-<h3> headings, in order: the report's sections for the Telegram message. */
function headings(storage: string): string[] {
  return [...storage.matchAll(/<h[1-3][^>]*>([\s\S]*?)<\/h[1-3]>/gi)]
    .map((m) => m[1].replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim())
    .filter(Boolean);
}

function pageId(value: unknown): string {
  const id = String(value ?? '').trim();
  if (!/^\d+$/.test(id)) {
    throw new ToolError(`"${value}" is not a page id (use the id from search_pages)`);
  }
  return id;
}
