import type { WSEvent, WorkflowState } from '@/lib/types'
import { getStreamEventText } from '@/lib/eventContent'

export interface EnrichedWSEvent {
  event: WSEvent
  /** Workflow state that was active when this event was emitted (after prior transitions). */
  workflowState: WorkflowState | null
}

/**
 * Replays the event list to attach the workflow state active at each message.
 * Requires `connection.state` early in the list or falls back to `fallbackState`.
 */
function isValidWsEvent(e: unknown): e is WSEvent {
  return (
    e != null &&
    typeof e === 'object' &&
    typeof (e as { type?: unknown }).type === 'string'
  )
}

export function enrichWorkflowEvents(
  events: WSEvent[],
  fallbackState: WorkflowState | null
): EnrichedWSEvent[] {
  let s: WorkflowState | null = fallbackState
  const out: EnrichedWSEvent[] = []

  for (const event of events) {
    if (!isValidWsEvent(event)) continue

    if (event.type === 'connection.state' && event.data) {
      const cs = (event.data as { current_state?: WorkflowState }).current_state
      if (cs) s = cs
      out.push({ event, workflowState: s })
      continue
    }

    out.push({ event, workflowState: s })

    if (event.type === 'workflow.state_changed') {
      const w = event as { to_state?: WorkflowState }
      if (w.to_state) s = w.to_state
    }
  }

  return out
}

/** Concatenate stream text from deltas that match optional phase filter. */
export function streamTextFromEvents(
  enriched: EnrichedWSEvent[],
  phaseId: string | null,
  phaseContainsFn: (phaseId: string, state: WorkflowState) => boolean
): string {
  const parts: string[] = []
  for (const { event, workflowState } of enriched) {
    if (!isValidWsEvent(event)) continue
    if (event.type !== 'agent.stream_delta' && event.type !== 'user.chat_response') {
      continue
    }
    const c = getStreamEventText(event)
    if (!c || !workflowState) continue
    if (phaseId !== null && !phaseContainsFn(phaseId, workflowState)) continue
    parts.push(c)
  }
  return parts.join('')
}
