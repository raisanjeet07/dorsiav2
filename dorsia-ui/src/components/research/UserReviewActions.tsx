'use client'

import { useState } from 'react'
import { api } from '@/lib/api'

interface UserReviewActionsProps {
  workflowId: string
  onDone?: () => void
}

export function UserReviewActions({ workflowId, onDone }: UserReviewActionsProps) {
  const [approveComment, setApproveComment] = useState('')
  const [changesDetail, setChangesDetail] = useState('')
  const [showChanges, setShowChanges] = useState(false)
  const [loading, setLoading] = useState<
    'approve' | 'changes' | 'cancel' | null
  >(null)
  const [error, setError] = useState<string | null>(null)

  const run = async (
    action: 'approve' | 'changes' | 'cancel',
    fn: () => Promise<unknown>
  ) => {
    setError(null)
    setLoading(action)
    try {
      await fn()
      onDone?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Action failed')
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="rounded-lg border border-[var(--bd)] bg-[var(--bg-2)] p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-[var(--t1)]">Decision</h3>
        <span className="text-xs text-[var(--t3)]">
          Approve to generate the final report, or request another revision
          cycle.
        </span>
      </div>

      {error && (
        <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded px-3 py-2">
          {error}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={loading !== null}
          onClick={() =>
            run('approve', () =>
              api.approveWorkflow(workflowId, approveComment.trim() || undefined)
            )
          }
          className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded text-sm font-medium disabled:opacity-50"
        >
          {loading === 'approve' ? 'Approving…' : 'Approve report'}
        </button>
        <button
          type="button"
          disabled={loading !== null}
          onClick={() => setShowChanges((v) => !v)}
          className="px-4 py-2 border border-[var(--bd)] text-[var(--t1)] rounded text-sm hover:bg-[var(--s2)] disabled:opacity-50"
        >
          {showChanges ? 'Hide changes form' : 'Request changes'}
        </button>
        <button
          type="button"
          disabled={loading !== null}
          onClick={() => {
            if (
              typeof window !== 'undefined' &&
              !window.confirm(
                'Cancel this workflow? This cannot be undone.'
              )
            ) {
              return
            }
            run('cancel', () => api.cancelWorkflow(workflowId))
          }}
          className="px-4 py-2 border border-red-500/40 text-red-400 rounded text-sm hover:bg-red-500/10 disabled:opacity-50"
        >
          {loading === 'cancel' ? 'Cancelling…' : 'Cancel workflow'}
        </button>
      </div>

      <div>
        <label className="block text-xs text-[var(--t3)] mb-1">
          Approval comment (optional)
        </label>
        <textarea
          value={approveComment}
          onChange={(e) => setApproveComment(e.target.value)}
          rows={2}
          placeholder="Notes for the final report…"
          className="w-full px-3 py-2 text-sm bg-[var(--bg)] border border-[var(--bd)] rounded text-[var(--t1)] focus:outline-none focus:ring-2 focus:ring-[var(--a5)]"
        />
      </div>

      {showChanges && (
        <div className="space-y-2 pt-2 border-t border-[var(--bd)]">
          <label className="block text-xs text-[var(--t3)]">
            What should be revised?
          </label>
          <textarea
            value={changesDetail}
            onChange={(e) => setChangesDetail(e.target.value)}
            rows={4}
            placeholder="Describe the changes you want…"
            className="w-full px-3 py-2 text-sm bg-[var(--bg)] border border-[var(--bd)] rounded text-[var(--t1)] focus:outline-none focus:ring-2 focus:ring-[var(--a5)]"
          />
          <button
            type="button"
            disabled={loading !== null || !changesDetail.trim()}
            onClick={() =>
              run('changes', () =>
                api.requestChanges(workflowId, {
                  message: changesDetail.trim(),
                  details: changesDetail.trim(),
                })
              )
            }
            className="px-4 py-2 bg-[var(--a5)] text-white rounded text-sm font-medium hover:bg-[var(--a4)] disabled:opacity-50"
          >
            {loading === 'changes' ? 'Submitting…' : 'Submit change request'}
          </button>
        </div>
      )}
    </div>
  )
}
