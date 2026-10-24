/**
 * Jira agent: prompt and tools.
 *
 * Read-only tools (it runs them during the loop):
 *   search_issues (JQL), get_issue, list_transitions
 * Anything that changes things is NOT done here: it goes into the plan (propose_plan)
 * and execute/actions.ts applies it after approval:
 *   create_issue, transition_issue, add_comment, assign_issue
 *
 * TODO (agents):
 * - [ ] System prompt: allowed project(s), ticket format, language.
 * - [ ] Tools with betaZodTool that call lib/jira.ts.
 * - [ ] Export the AgentSpec for agents/loop.ts.
 */
import type { AgentSpec } from './loop';

export const jiraAgent: AgentSpec = {
  name: 'jira',
  system: 'TODO: Jira agent prompt',
  tools: [],   // TODO
};
