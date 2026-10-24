/**
 * Reporter agent: prompt and tools.
 *
 * Gathers information from Jira (and Confluence) and proposes a report: sprint
 * summary, status of an epic, someone's pending work, etc.
 *   Read: search_issues, get_page
 *   In the plan: create_page / update_page in Confluence, send_message through Telegram
 *
 * TODO (agents):
 * - [ ] System prompt: report format, tone and length.
 * - [ ] Tools with betaZodTool that call lib/jira.ts and lib/confluence.ts.
 * - [ ] Export the AgentSpec for agents/loop.ts.
 */
import type { AgentSpec } from './loop';

export const reporterAgent: AgentSpec = {
  name: 'reporter',
  system: 'TODO: reporter prompt',
  tools: [],   // TODO
};
