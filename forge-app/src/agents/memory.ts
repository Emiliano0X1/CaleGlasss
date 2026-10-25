/**
 * The agents' memory: notes in the stdb `memory` table (path -> content), shared by every agent.
 *
 *   withMemory(spec)   the agent with the saved notes at the start of its prompt and one more
 *                      tool, save_note(path, text) -> memory_write
 *
 * queue/consumer.ts wraps each agent with it before running it, so a note saved in one run
 * (e.g. the team's new report format) is in the prompt of the next one.
 *
 * Paths group the notes: 'people/<name>' (who someone is in Jira), '<agent>/<topic>'
 * ('reporter/report-format'). Saving to an existing path replaces that note.
 */
import { type AgentSpec, type AgentTool, ToolError } from './loop';
import { call, sql } from '../lib/stdb';

const MAX_NOTE = 2000;
const MAX_NOTES_CHARS = 8000;   // all the notes together, to keep the prompt short
const PATH = /^[a-z0-9_-]+(\/[a-z0-9_-]+)*$/;

export async function readNotes(): Promise<{ path: string; content: string }[]> {
  const rows = await sql('SELECT path, content FROM memory');
  return rows.map(([path, content]) => ({ path: String(path), content: String(content) })).sort((a, b) => a.path.localeCompare(b.path));
}

export async function withMemory(spec: AgentSpec): Promise<AgentSpec> {
  let notes: { path: string; content: string }[] = [];
  try {
    notes = await readNotes();
  } catch (e) {
    console.error('memory: reading the notes failed, running without them:', e);   // memory helps, it isn't required
  }
  const list = notes.map((n) => `- ${n.path}: ${n.content}`).join('\n').slice(0, MAX_NOTES_CHARS);
  const header = `Team notes (saved by you or by other agents in earlier runs; trust them, they're facts about this team):
${list || '- (none yet)'}

To remember something for future runs, call save_note. Reusing a path replaces that note.

`;
  return { ...spec, system: header + spec.system, tools: [...spec.tools, saveNote(spec.name)] };
}

function saveNote(agent: string): AgentTool {
  return {
    definition: {
      name: 'save_note',
      description:
        'Save a note for future runs of every agent (a fact about the team: who someone is, a format the team wants). Reusing a path replaces the note.',
      input_schema: {
        type: 'object',
        properties: {
          path: { type: 'string', description: "Short lowercase key, e.g. 'people/ana' or 'reporter/report-format'" },
          text: { type: 'string', description: 'The note, one or two sentences' },
        },
        required: ['path', 'text'],
        additionalProperties: false,
      },
    },
    run: async ({ path, text }) => {
      const key = String(path ?? '').trim().toLowerCase();
      const content = String(text ?? '').trim();
      if (!PATH.test(key) || key.length > 80) {
        throw new ToolError(`"${path}" isn't a valid path: lowercase words separated by "/", e.g. people/ana`);
      }
      if (!content || content.length > MAX_NOTE) {
        throw new ToolError(`text must be 1-${MAX_NOTE} characters`);
      }
      await call('memory_write', [key, content]);
      await call('log_event', [agent, `note saved: ${key}`]);
      console.log(`memory: ${agent} saved ${key}`);
      return { content: { ok: true, path: key } };
    },
  };
}
