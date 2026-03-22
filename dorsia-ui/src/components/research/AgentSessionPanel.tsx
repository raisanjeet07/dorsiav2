'use client'

import type { AgentSessionRow } from '@/lib/types'

export function AgentSessionPanel({ sessions }: { sessions: AgentSessionRow[] }) {
  if (sessions.length === 0) {
    return (
      <p className="text-xs text-[var(--t3)]">
        No gateway sessions yet. When a phase starts, session id, flow, workspace,
        and PID (if reported by the gateway) appear here.
      </p>
    )
  }

  return (
    <ul className="space-y-2 max-h-48 overflow-y-auto text-xs">
      {sessions.map((s) => (
        <li
          key={`${s.session_id}:${s.flow}`}
          className="border border-[var(--bd)] rounded p-2 bg-[var(--bg)]"
        >
          <div className="flex flex-col gap-0.5">
            <span className="text-[var(--t3)]">Role</span>
            <span className="text-[var(--t1)] font-medium whitespace-pre-wrap break-words">
              {s.role}
            </span>
          </div>
          <div className="flex flex-col gap-0.5 mt-2">
            <span className="text-[var(--t3)]">Session</span>
            <code className="text-[var(--b4)] whitespace-pre-wrap break-all">
              {s.session_id}
            </code>
          </div>
          <div className="flex flex-col gap-0.5 mt-2">
            <span className="text-[var(--t3)]">Flow</span>
            <code className="text-[var(--t2)]">{s.flow}</code>
          </div>
          <div className="flex flex-col gap-0.5 mt-2">
            <span className="text-[var(--t3)]">Workspace</span>
            <span className="text-[var(--t2)] whitespace-pre-wrap break-words">
              {s.workspace_dir || '—'}
            </span>
          </div>
          <div className="flex justify-between gap-2 mt-1">
            <span className="text-[var(--t3)]">PID</span>
            <span className="text-[var(--t1)]">
              {s.process_id != null ? s.process_id : '—'}
            </span>
          </div>
          <div className="flex justify-between gap-2 mt-1">
            <span className="text-[var(--t3)]">Status</span>
            <span
              className={
                s.status === 'active' ? 'text-green-400' : 'text-[var(--t3)]'
              }
            >
              {s.status}
            </span>
          </div>
        </li>
      ))}
    </ul>
  )
}
