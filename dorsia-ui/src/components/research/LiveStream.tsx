'use client'
import { useEffect, useRef } from 'react'

interface LiveStreamProps {
  /** Live chunks (ignored if `text` is passed). */
  chunks?: string[]
  /** Full text to show (e.g. phase-filtered history). */
  text?: string
  activeAgent?: string
  /** When true, hide streaming cursor (e.g. history mode). */
  historyMode?: boolean
}

export function LiveStream({
  chunks = [],
  text,
  activeAgent,
  historyMode = false,
}: LiveStreamProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  const fullText = text !== undefined ? text : chunks.join('')

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [fullText])

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      {activeAgent && (
        <div className="flex shrink-0 items-center gap-2 rounded border border-[var(--bd)] bg-[var(--bg-2)] px-3 py-1.5">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-[var(--a5)] animate-pulse" />
            <span className="text-xs font-medium text-[var(--t2)]">
              {activeAgent}
            </span>
          </div>
        </div>
      )}

      <div
        ref={containerRef}
        className="min-h-0 flex-1 overflow-y-auto rounded border border-[var(--bd)] bg-[var(--bg-2)] p-3 font-mono text-sm text-[var(--t1)] whitespace-pre-wrap break-words"
      >
        {fullText || (
          <span className="text-[var(--t3)]">Waiting for stream...</span>
        )}
        {!historyMode && chunks.length > 0 && (
          <span className="animate-pulse ml-1">▌</span>
        )}
      </div>
    </div>
  )
}
