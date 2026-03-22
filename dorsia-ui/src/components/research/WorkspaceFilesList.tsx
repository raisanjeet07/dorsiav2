'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { WorkspaceFileEntry } from '@/lib/types'

export function WorkspaceFilesList({
  workflowId,
  pollMs = 8000,
}: {
  workflowId: string
  pollMs?: number
}) {
  const [path, setPath] = useState<string>('')
  const [files, setFiles] = useState<WorkspaceFileEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const data = await api.listWorkspaceFiles(workflowId)
        if (cancelled) return
        setPath(data.workspace_path)
        setFiles(data.files)
        setErr(null)
      } catch (e) {
        if (!cancelled) {
          setErr(e instanceof Error ? e.message : 'Failed to load files')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    const t = setInterval(load, pollMs)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [workflowId, pollMs])

  if (loading) {
    return <p className="text-xs text-[var(--t3)]">Loading workspace files…</p>
  }
  if (err) {
    return <p className="text-xs text-red-400">{err}</p>
  }

  return (
    <div className="text-xs">
      <p className="text-[var(--t3)] mb-2 whitespace-pre-wrap break-words">
        {path}
      </p>
      {files.length === 0 ? (
        <p className="text-[var(--t3)]">No files yet.</p>
      ) : (
        <ul className="max-h-40 overflow-y-auto space-y-1 font-mono">
          {files.map((f, i) => (
            <li
              key={f.path || `f-${i}`}
              className="flex flex-col sm:flex-row sm:justify-between gap-1 text-[var(--t2)]"
            >
              <span className="whitespace-pre-wrap break-words min-w-0">
                {f.path ?? '—'}
              </span>
              <span className="text-[var(--t3)] shrink-0">
                {(() => {
                  const n = Number(f.size_bytes)
                  return Number.isFinite(n) ? `${n.toLocaleString()} B` : '—'
                })()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
