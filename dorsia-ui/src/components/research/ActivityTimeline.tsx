'use client'

import { useRef, useEffect } from 'react'
import type { EnrichedWSEvent } from '@/lib/enrichWorkflowEvents'
import { safeReactText } from '@/lib/safeReactText'

function formatTime(iso?: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return '—'
  }
}

function eventSummary(e: EnrichedWSEvent): string {
  const { event } = e
  const typeStr =
    typeof event.type === 'string' ? event.type : safeReactText(event.type)
  switch (typeStr) {
    case 'workflow.state_changed': {
      const w = event as { from_state?: string; to_state?: string }
      return `${w.from_state ?? '?'} → ${w.to_state ?? '?'}`
    }
    case 'agent.stream_delta':
      return 'stream Δ'
    case 'agent.stream_start': {
      const r = (event as { role?: string }).role
      return `stream start${r ? ` (${r})` : ''}`
    }
    case 'agent.stream_end':
      return 'stream end'
    case 'agent.session': {
      const s = (event as { status?: string }).status
      return `session ${s ?? ''}`
    }
    case 'agent.status':
      return `status ${(event as { status?: string }).status ?? ''}`
    case 'review.comments':
      return 'review comments'
    case 'resolution.merged':
      return 'resolution merged'
    case 'report.updated':
      return 'report updated'
    case 'workflow.completed':
      return 'completed'
    case 'workflow.error':
      return 'error'
    case 'user.chat_response':
      return 'chat response'
    default:
      return typeStr
  }
}

interface ActivityTimelineProps {
  enriched: EnrichedWSEvent[]
  onSelectIndex?: (globalIndex: number) => void
  /** Tighter single-row strip for dense layouts (workflow header). */
  compact?: boolean
}

/** Horizontal activity strip — latest events on the right; scroll end follows new events. */
export function ActivityTimeline({
  enriched,
  onSelectIndex,
  compact = false,
}: ActivityTimelineProps) {
  const scrollerRef = useRef<HTMLDivElement>(null)
  const tail = enriched.slice(compact ? -24 : -48)

  useEffect(() => {
    const el = scrollerRef.current
    if (el) el.scrollLeft = el.scrollWidth
  }, [enriched.length])

  if (tail.length === 0) {
    return (
      <div
        className={`text-[var(--t3)] ${compact ? 'py-1 text-[10px]' : 'text-xs py-2 border-b border-[var(--bd)]'}`}
      >
        No activity yet — events from the research service will appear here.
      </div>
    )
  }

  if (compact) {
    return (
      <div className="flex min-h-0 flex-col gap-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--t3)]">
            Activity
          </span>
          <span className="text-[10px] text-[var(--t4)]">
            {enriched.length} evt
          </span>
        </div>
        <div
          ref={scrollerRef}
          className="flex max-h-9 gap-1.5 overflow-x-auto overflow-y-hidden pb-0.5 scrollbar-thin"
        >
          {tail.map((item, i) => {
            const globalIndex = enriched.length - tail.length + i
            const ts = (item.event as { timestamp?: string }).timestamp as
              | string
              | undefined
            return (
              <button
                key={`${globalIndex}-${ts ?? i}`}
                type="button"
                onClick={() => onSelectIndex?.(globalIndex)}
                className="flex h-8 max-w-[min(11rem,40vw)] flex-shrink-0 items-center gap-1.5 rounded border border-[var(--bd)] bg-[var(--bg)] px-2 text-left hover:bg-[var(--s2)]"
                title={`${safeReactText(item.event.type)} — ${eventSummary(item)}`}
              >
                <span className="font-mono text-[9px] text-[var(--t4)]">
                  {formatTime(ts)}
                </span>
                <span className="truncate text-[10px] font-medium text-[var(--a5)]">
                  {safeReactText(item.event.type)}
                </span>
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div className="border-b border-[var(--bd)] pb-3 mb-3">
      <div className="flex items-center justify-between gap-2 mb-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--t3)]">
          Activity
        </h2>
        <span className="text-[10px] text-[var(--t4)]">
          {enriched.length} event{enriched.length === 1 ? '' : 's'}
        </span>
      </div>
      <div
        ref={scrollerRef}
        className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin"
      >
        {tail.map((item, i) => {
          const globalIndex = enriched.length - tail.length + i
          const ts = (item.event as { timestamp?: string }).timestamp as
            | string
            | undefined
          return (
            <button
              key={`${globalIndex}-${ts ?? i}`}
              type="button"
              onClick={() => onSelectIndex?.(globalIndex)}
              className="flex-shrink-0 text-left px-2 py-1.5 rounded border border-[var(--bd)] bg-[var(--bg-2)] hover:bg-[var(--s2)] transition-colors max-w-[200px]"
            >
              <div className="text-[10px] text-[var(--t4)] font-mono">
                {formatTime(ts)}
              </div>
              <div className="text-[11px] text-[var(--a5)] font-medium truncate">
                {safeReactText(item.event.type)}
              </div>
              <div className="text-[10px] text-[var(--t2)] truncate">
                {eventSummary(item)}
              </div>
              {item.workflowState && (
                <div className="text-[9px] text-[var(--t4)] truncate mt-0.5">
                  @{safeReactText(item.workflowState)}
                </div>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
