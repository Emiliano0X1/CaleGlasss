/**
 * Five blocks, all live from SpacetimeDB subscriptions (no reloads, no polling):
 *   Agents     each agent's last heartbeat (agents)
 *   Work       work items, with "waiting on …" while their depends_on isn't done (work_items)
 *   Pending    plans waiting for approval, with an Approve button (proposals, status 'pending')
 *   Events     the event feed, newest first (events)
 *   Log        what was changed, who approved it and from where (proposals + actions)
 */
import { useEffect, useState } from 'react'
import { useSpacetimeDB, useTable } from 'spacetimedb/react'
import type { Timestamp } from 'spacetimedb'
import { tables } from './module_bindings'
import type { Actions, Proposals, WorkItems } from './module_bindings/types'
import { approveConfigured, approveFromPanel } from './approve'

const EVENTS_SHOWN = 50
const AGENT_STALE_S = 120            // no heartbeat for this long: shown as offline
const BOOKKEEPING = new Set(['approve', 'reject'])   // voice approvals are work items too; not shown under Work
const DECIDED = new Set(['approved', 'executing', 'done', 'failed', 'rejected'])

function useNow(intervalMs = 5000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

const ms = (t: Timestamp) => t.toDate().getTime()
const clock = (t: Timestamp) => t.toDate().toLocaleTimeString()

function ago(t: Timestamp, now: number): string {
  const s = Math.max(0, Math.round((now - ms(t)) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  return clock(t)
}

export default function App() {
  const conn = useSpacetimeDB()
  const [agents, agentsReady] = useTable(tables.agents)
  const [works] = useTable(tables.workItems)
  const [proposals] = useTable(tables.proposals)
  const [events] = useTable(tables.events)
  const [actions] = useTable(tables.actions)
  const now = useNow()

  const workById = new Map(works.map((w) => [w.id, w]))
  const pending = proposals.filter((p) => p.status === 'pending')
  const decided = proposals.filter((p) => DECIDED.has(p.status))
  const actionsByProposal = new Map<string, Actions[]>()
  for (const a of actions) {
    actionsByProposal.set(a.proposalId, [...(actionsByProposal.get(a.proposalId) ?? []), a])
  }
  const newestFirst = <T,>(rows: readonly T[], at: (row: T) => number) => [...rows].sort((a, b) => at(b) - at(a))
  const workAt = (p: Proposals) => {
    const w = workById.get(p.workId)
    return w ? ms(w.createdAt) : 0
  }

  return (
    <main>
      <header>
        <h1>Agent team</h1>
        <span className={`conn ${conn.isActive ? 'on' : 'off'}`}>
          {conn.isActive ? 'live' : conn.connectionError ? `error: ${conn.connectionError.message}` : 'connecting…'}
        </span>
      </header>

      <section className="agents">
        <h2>Agents</h2>
        {agentsReady && agents.length === 0 && <p className="empty">No agent has reported yet.</p>}
        <ul>
          {[...agents].sort((a, b) => a.name.localeCompare(b.name)).map((a) => {
            const stale = (now - ms(a.lastSeen)) / 1000 > AGENT_STALE_S
            return (
              <li key={a.name} className={stale ? 'stale' : ''}>
                <strong>{a.name}</strong>
                <span className="status">{stale ? 'offline' : a.status || 'idle'}</span>
                {a.workId && <code>{a.workId}</code>}
                <small>{ago(a.lastSeen, now)}</small>
              </li>
            )
          })}
        </ul>
      </section>

      <section className="work">
        <h2>Work</h2>
        <ul>
          {newestFirst(works.filter((w) => !BOOKKEEPING.has(w.type)), (w) => ms(w.createdAt)).map((w) => (
            <WorkRow key={w.id} work={w} dependency={w.dependsOn ? workById.get(w.dependsOn) : undefined} />
          ))}
        </ul>
      </section>

      <section className="pending">
        <h2>Pending plans</h2>
        {pending.length === 0 && <p className="empty">Nothing waiting for approval.</p>}
        <ul>
          {newestFirst(pending, workAt).map((p) => (
            <PendingRow key={p.id} proposal={p} request={workById.get(p.workId)?.text} />
          ))}
        </ul>
      </section>

      <section className="events">
        <h2>Events</h2>
        <ul>
          {newestFirst(events, (e) => ms(e.date)).slice(0, EVENTS_SHOWN).map((e) => (
            <li key={String(e.id)}>
              <small>{clock(e.date)}</small> <strong>{e.actor}</strong> {e.text}
            </li>
          ))}
        </ul>
      </section>

      <section className="log">
        <h2>Log</h2>
        {decided.length === 0 && <p className="empty">No plan decided yet.</p>}
        <ul>
          {newestFirst(decided, workAt).map((p) => (
            <LogRow key={p.id} proposal={p} actions={actionsByProposal.get(p.id) ?? []} />
          ))}
        </ul>
      </section>
    </main>
  )
}

function WorkRow({ work, dependency }: { work: WorkItems; dependency?: WorkItems }) {
  const waiting = work.dependsOn && dependency?.status !== 'done'
  return (
    <li>
      <span className={`badge ${work.status}`}>{work.status}</span>
      <span className="text">{work.text}</span>
      {work.claimedBy && <small>· {work.claimedBy}</small>}
      {waiting && (
        <small className="waiting">
          waiting on {dependency ? `"${dependency.text}" (${dependency.status})` : work.dependsOn}
        </small>
      )}
    </li>
  )
}

function PendingRow({ proposal, request }: { proposal: Proposals; request?: string }) {
  const [state, setState] = useState<{ busy: boolean; note?: string }>({ busy: false })

  async function onApprove() {
    setState({ busy: true })
    try {
      const result = await approveFromPanel(proposal.id)
      // 'approved' -> the row disappears by itself when stdb updates; anything else stays visible
      setState({ busy: false, note: result === 'approved' ? undefined : result })
    } catch (e) {
      setState({ busy: false, note: e instanceof Error ? e.message : String(e) })
    }
  }

  return (
    <li>
      <div className="summary">{proposal.summary}</div>
      {request && <small>request: {request}</small>}
      <PlanActions json={proposal.actions} />
      <div className="row">
        <small>
          {proposal.agent} · <code>{proposal.id}</code>
        </small>
        <button onClick={onApprove} disabled={state.busy || !approveConfigured}
          title={approveConfigured ? '' : 'Set VITE_GLASSES_WEBTRIGGER_URL and VITE_APPROVAL_SECRET in .env.local'}>
          {state.busy ? 'Approving…' : 'Approve'}
        </button>
      </div>
      {state.note && <small className="error">{state.note}</small>}
    </li>
  )
}

/** The proposed actions, from the JSON the agent saved as text. */
function PlanActions({ json }: { json: string }) {
  let steps: Record<string, unknown>[]
  try {
    const parsed = JSON.parse(json)
    steps = Array.isArray(parsed) ? parsed : []
  } catch {
    return null
  }
  return (
    <ol>
      {steps.map((step, i) => {
        const { type, issue, ...rest } = step
        const details = Object.entries(rest).map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
        return (
          <li key={i}>
            <code>{String(type)}</code> {issue ? <strong>{String(issue)}</strong> : null} {details.join(', ')}
          </li>
        )
      })}
    </ol>
  )
}

function LogRow({ proposal, actions }: { proposal: Proposals; actions: Actions[] }) {
  return (
    <li>
      <div className="row">
        <span className={`badge ${proposal.status}`}>{proposal.status}</span>
        <span className="text">{proposal.summary}</span>
      </div>
      <small>
        {proposal.status === 'rejected' ? 'rejected' : 'approved'} by <strong>{proposal.approvedBy || '?'}</strong> via{' '}
        <strong>{proposal.approvedVia || '?'}</strong>
      </small>
      {actions.length > 0 && (
        <ul className="changes">
          {[...actions].sort((a, b) => ms(a.date) - ms(b.date)).map((a) => (
            <li key={String(a.id)}>
              <code>{a.type}</code> <strong>{a.target}</strong> {a.before || '—'} → {a.after || '—'}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}
