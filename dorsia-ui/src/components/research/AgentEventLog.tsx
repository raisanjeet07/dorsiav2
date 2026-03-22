'use client'

import { useEffect, useRef, useMemo } from 'react'
import type { EnrichedWSEvent } from '@/lib/enrichWorkflowEvents'
import type { WorkflowState } from '@/lib/types'
import { safeReactText } from '@/lib/safeReactText'

function safeJson(e: unknown): string {
  try {
    return JSON.stringify(e, null, 2)
  } catch {
    return String(e)
  }
}

interface AgentEventLogProps {
  enriched: EnrichedWSEvent[]
  /** When set, only show events whose workflow state belongs to this phase */
  phaseFilterId: string | null
  phaseContains: (phaseId: string, state: WorkflowState) => boolean
  scrollToIndex?: number | null
}

export function AgentEventLog({
  enriched,
  phaseFilterId,
  phaseContains,
  scrollToIndex,
}: AgentEventLogProps) {
  const rowRefs = useRef<Map<number, HTMLDivElement>>(new Map())

  const rows = useMemo(() => {
    return enriched
      .map((event, idx) => ({ event, idx }))
      .filter(
        ({ event }) =>
          phaseFilterId === null ||
          (event.workflowState != null &&
            phaseContains(phaseFilterId, event.workflowState))
      )
  }, [enriched, phaseFilterId, phaseContains])

  useEffect(() => {
    if (scrollToIndex == null) return
    const el = rowRefs.current.get(scrollToIndex)
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [scrollToIndex, rows.length])

  return (
    <div className="flex flex-col h-full min-h-0 border border-[var(--bd)] rounded bg-[var(--bg-2)]">
      <div className="px-3 py-2 border-b border-[var(--bd)] text-xs font-medium text-[var(--t2)]">
        Agent & workflow events
        {phaseFilterId !== null && (
          <span className="text-[var(--t3)] ml-2">(filtered by phase)</span>
        )}
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
        {rows.length === 0 ? (
          <p className="text-xs text-[var(--t3)] p-2">
            No events in this view.
          </p>
        ) : (
          rows.map(({ event: item, idx }) => {
            const ts = (item.event as { timestamp?: string }).timestamp as
              | string
              | undefined
            return (
              <div
                key={`${idx}-${ts}-${safeReactText(item.event.type)}`}
                ref={(el) => {
                  if (el) rowRefs.current.set(idx, el)
                  else rowRefs.current.delete(idx)
                }}
                className="rounded border border-[var(--bd)] bg-[var(--bg)] p-2 text-xs"
              >
                <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-[var(--t4)] mb-1">
                  {ts && (
                    <span className="font-mono">
                      {new Date(ts).toLocaleString()}
                    </span>
                  )}
                  <span className="text-[var(--a5)] font-medium">
                    {safeReactText(item.event.type)}
                  </span>
                  {item.workflowState && (
                    <span className="text-[var(--t3)]">
                      state: {safeReactText(item.workflowState)}
                    </span>
                  )}
                </div>
                <pre className="text-[11px] text-[var(--t2)] whitespace-pre-wrap break-words overflow-x-auto max-h-40 overflow-y-auto font-mono">
                  {safeJson(item.event)}
                </pre>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
