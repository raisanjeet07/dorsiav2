'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { api } from '@/lib/api'
import type { Workflow } from '@/lib/types'
import { StatusPill } from '@/components/research/StatusPill'

export default function ResearchListPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const fetchWorkflows = async () => {
    try {
      setError(null)
      const data = await api.listWorkflows({ limit: 50 })
      setWorkflows(data.workflows ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workflows')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchWorkflows()
    const interval = setInterval(fetchWorkflows, 5000)
    return () => clearInterval(interval)
  }, [])

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const copyWorkflowLink = async (workflowId: string) => {
    const url = `${typeof window !== 'undefined' ? window.location.origin : ''}/research/${workflowId}`
    try {
      await navigator.clipboard.writeText(url)
      setCopiedId(workflowId)
      window.setTimeout(() => setCopiedId(null), 2000)
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-[var(--bg)] text-[var(--t1)]">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold mb-2">Research Workflows</h1>
            <p className="text-[var(--t2)]">
              Manage and monitor your research workflows
            </p>
          </div>
          <Link
            href="/research/new"
            className="px-4 py-2 bg-[var(--a5)] text-white rounded font-medium hover:bg-[var(--a4)] transition-colors"
          >
            New Research
          </Link>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-500/10 text-red-400 rounded border border-red-500/30">
            {error}
          </div>
        )}

        <div className="bg-[var(--bg-2)] rounded border border-[var(--bd)] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--bd)]">
                  <th className="px-6 py-3 text-left text-sm font-semibold text-[var(--t2)]">
                    Topic
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-[var(--t2)]">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-[var(--t2)]">
                    Depth
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-[var(--t2)]">
                    Cycle
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-[var(--t2)]">
                    Created
                  </th>
                  <th className="px-6 py-3 text-right text-sm font-semibold text-[var(--t2)]">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-8 text-center text-[var(--t3)]">
                      Loading workflows...
                    </td>
                  </tr>
                ) : workflows.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-8 text-center text-[var(--t3)]">
                      No workflows yet
                    </td>
                  </tr>
                ) : (
                  workflows.map((workflow) => (
                    <tr
                      key={workflow.workflow_id}
                      className="border-t border-[var(--bd)] hover:bg-[var(--bg-3)] transition-colors"
                    >
                      <td className="px-6 py-4">
                        <Link
                          href={`/research/${workflow.workflow_id}`}
                          title={workflow.topic}
                          className="block max-w-xs truncate font-medium text-[var(--t1)] hover:text-[var(--a5)] hover:underline"
                        >
                          {workflow.topic}
                        </Link>
                      </td>
                      <td className="px-6 py-4">
                        <StatusPill state={workflow.current_state} />
                      </td>
                      <td className="px-6 py-4 text-sm text-[var(--t2)]">
                        {workflow.depth}
                      </td>
                      <td className="px-6 py-4 text-sm text-[var(--t2)]">
                        {workflow.review_cycle}
                      </td>
                      <td className="px-6 py-4 text-sm text-[var(--t2)]">
                        {formatDate(workflow.created_at)}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex flex-wrap items-center justify-end gap-2 sm:gap-3">
                          <Link
                            href={`/research/${workflow.workflow_id}`}
                            className="text-[var(--a5)] hover:text-[var(--a4)] font-medium text-sm"
                          >
                            View
                          </Link>
                          <a
                            href={`/research/${workflow.workflow_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm text-[var(--t3)] hover:text-[var(--t1)] whitespace-nowrap"
                          >
                            Open
                          </a>
                          <button
                            type="button"
                            onClick={() => copyWorkflowLink(workflow.workflow_id)}
                            className="text-sm text-[var(--t3)] hover:text-[var(--t1)] whitespace-nowrap"
                          >
                            {copiedId === workflow.workflow_id
                              ? 'Copied'
                              : 'Copy link'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {workflows.length > 0 && (
          <div className="mt-6 text-center text-sm text-[var(--t3)]">
            Showing {workflows.length} workflows. Auto-refreshing every 5 seconds.
          </div>
        )}
      </div>
    </div>
  )
}
