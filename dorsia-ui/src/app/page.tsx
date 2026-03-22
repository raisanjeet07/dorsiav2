'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { api } from '@/lib/api'
import type { Workflow } from '@/lib/types'

export default function Home() {
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [stats, setStats] = useState({
    active: 0,
    completed: 0,
    /** Research service → CLI gateway WebSocket (from /health). */
    gatewayConnected: false,
    apiHealthy: true,
    databaseReady: true,
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true)
        setError(null)

        // Fetch health status
        try {
          const health = await api.health()
          setStats((prev) => ({
            ...prev,
            apiHealthy: health.status === 'healthy',
            gatewayConnected: health.gateway_connected,
            databaseReady: health.database_ready,
          }))
        } catch {
          setStats((prev) => ({
            ...prev,
            apiHealthy: false,
            gatewayConnected: false,
            databaseReady: false,
          }))
        }

        // Fetch workflows
        const result = await api.listWorkflows()
        setWorkflows(result.workflows || [])

        // Calculate stats
        const active = result.workflows?.filter(
          (w) => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(w.current_state)
        ).length || 0
        const completed = result.workflows?.filter((w) => w.current_state === 'COMPLETED').length || 0

        setStats((prev) => ({
          ...prev,
          active,
          completed,
        }))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load data')
        // Set empty state on error
        setWorkflows([])
      } finally {
        setLoading(false)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 30000) // Refresh every 30 seconds
    return () => clearInterval(interval)
  }, [])

  const greeting = (() => {
    const h = new Date().getHours()
    if (h < 12) return 'Good morning'
    if (h < 17) return 'Good afternoon'
    return 'Good evening'
  })()

  // Get status color and label
  const getStatusColor = (state: string) => {
    if (state === 'USER_REVIEW') return 'bg-amber-500/20 text-amber-500 border border-amber-500/30'
    if (['RESEARCHING', 'REVIEWING', 'RESOLVING', 'RE_REVIEWING'].includes(state))
      return 'bg-blue-500/20 text-blue-500 border border-blue-500/30'
    if (state === 'COMPLETED') return 'bg-green-500/20 text-green-500 border border-green-500/30'
    if (['FAILED', 'CANCELLED'].includes(state)) return 'bg-red-500/20 text-red-500 border border-red-500/30'
    return 'bg-slate-500/20 text-slate-500 border border-slate-500/30'
  }

  const getStatusLabel = (state: string) => {
    const labels: Record<string, string> = {
      INITIATED: 'Initiated',
      RESEARCHING: 'Researching',
      RESEARCH_COMPLETE: 'Research Complete',
      REVIEWING: 'Reviewing',
      REVIEW_COMPLETE: 'Review Complete',
      RESOLVING: 'Resolving',
      RESOLUTION_COMPLETE: 'Resolution Complete',
      RE_REVIEWING: 'Re-Reviewing',
      CONSENSUS_REACHED: 'Consensus Reached',
      USER_REVIEW: 'Awaiting Review',
      USER_APPROVED: 'Approved',
      GENERATING_FINAL: 'Generating Final',
      COMPLETED: 'Completed',
      FAILED: 'Failed',
      CANCELLED: 'Cancelled',
    }
    return labels[state] || state
  }

  const userReviewWorkflows = workflows.filter((w) => w.current_state === 'USER_REVIEW')
  const activeWorkflows = workflows.filter(
    (w) => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(w.current_state)
  )

  return (
    <main className="w-full max-w-full px-4 py-6 sm:px-8 sm:py-10 pb-16">
      <div className="flex-1 p-8 space-y-8">
        {/* Header with Greeting */}
        <div>
          <h1 className="text-3xl font-bold text-[var(--t1)] mb-2">{greeting}</h1>
          <p className="text-[var(--t3)]">Research workflows — API and gateway status below</p>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-3 gap-4">
          {/* Active Research */}
          <div className="rounded-lg border border-[var(--bd)] bg-[var(--s1)] p-6">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-sm font-medium text-[var(--t3)] mb-2">Active Research</p>
                <p className="text-4xl font-bold text-[var(--t1)]">{stats.active}</p>
              </div>
              <div className="p-2 rounded-lg bg-blue-500/20">
                <svg className="w-6 h-6 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
            </div>
          </div>

          {/* Completed Research */}
          <div className="rounded-lg border border-[var(--bd)] bg-[var(--s1)] p-6">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-sm font-medium text-[var(--t3)] mb-2">Completed</p>
                <p className="text-4xl font-bold text-[var(--t1)]">{stats.completed}</p>
              </div>
              <div className="p-2 rounded-lg bg-green-500/20">
                <svg className="w-6 h-6 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
            </div>
          </div>

          {/* Gateway + API health */}
          <div className="rounded-lg border border-[var(--bd)] bg-[var(--s1)] p-6">
            <div className="flex items-start justify-between">
              <div className="space-y-2 min-w-0">
                <p className="text-sm font-medium text-[var(--t3)]">Systems</p>
                <p className="text-sm font-semibold flex flex-wrap gap-2">
                  <span
                    className={`inline-block px-2 py-1 rounded text-xs font-medium ${
                      stats.apiHealthy
                        ? 'bg-green-500/20 text-green-500'
                        : 'bg-red-500/20 text-red-500'
                    }`}
                  >
                    API {stats.apiHealthy ? 'up' : 'down'}
                  </span>
                  <span
                    className={`inline-block px-2 py-1 rounded text-xs font-medium ${
                      stats.gatewayConnected
                        ? 'bg-green-500/20 text-green-500'
                        : 'bg-amber-500/20 text-amber-500'
                    }`}
                    title="Research service WebSocket to the CLI gateway"
                  >
                    Gateway {stats.gatewayConnected ? 'connected' : 'idle'}
                  </span>
                </p>
                {!stats.databaseReady && (
                  <p className="text-xs text-amber-500">Database not ready</p>
                )}
              </div>
              <div
                className={`p-2 rounded-lg shrink-0 ${
                  stats.gatewayConnected && stats.apiHealthy
                    ? 'bg-green-500/20'
                    : 'bg-amber-500/20'
                }`}
              >
                <svg
                  className={`w-6 h-6 ${
                    stats.gatewayConnected && stats.apiHealthy
                      ? 'text-green-500'
                      : 'text-amber-500'
                  }`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 12l2 2 4-4m7 0a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
              </div>
            </div>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-500">
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Needs Your Attention */}
        {userReviewWorkflows.length > 0 && (
          <div>
            <h2 className="text-lg font-semibold text-[var(--t1)] mb-4">Needs Your Attention</h2>
            <div className="space-y-2">
              {userReviewWorkflows.map((workflow) => (
                <Link
                  key={workflow.workflow_id}
                  href={`/research/${workflow.workflow_id}`}
                  className="block rounded-lg border border-[var(--bd)] bg-[var(--s1)] p-4 hover:bg-[var(--s2)] transition-colors group"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <h3 className="font-medium text-[var(--t1)] group-hover:text-amber-400">{workflow.topic}</h3>
                      <p className="text-sm text-[var(--t3)]">{workflow.context}</p>
                    </div>
                    <span
                      className={`ml-4 px-3 py-1 rounded-full text-xs font-semibold whitespace-nowrap ${getStatusColor(
                        workflow.current_state
                      )}`}
                    >
                      {getStatusLabel(workflow.current_state)}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* Active Research Flows */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-[var(--t1)]">Active Research Flows</h2>
            <Link
              href="/research/new"
              className="text-amber-500 hover:text-amber-400 text-sm font-medium transition-colors"
            >
              + New Research
            </Link>
          </div>

          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-16 rounded-lg border border-[var(--bd)] bg-[var(--s1)] animate-pulse"
                />
              ))}
            </div>
          ) : activeWorkflows.length > 0 ? (
            <div className="space-y-2">
              {activeWorkflows.map((workflow) => (
                <Link
                  key={workflow.workflow_id}
                  href={`/research/${workflow.workflow_id}`}
                  className="block rounded-lg border border-[var(--bd)] bg-[var(--s1)] p-4 hover:bg-[var(--s2)] transition-colors group"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-[var(--t1)] group-hover:text-amber-400 truncate">
                        {workflow.topic}
                      </h3>
                      <p className="text-sm text-[var(--t3)] truncate">{workflow.context}</p>
                      <p className="text-xs text-[var(--t4)] mt-1">
                        Updated {new Date(workflow.updated_at).toLocaleDateString()}
                      </p>
                    </div>
                    <div className="flex items-center gap-4 ml-4">
                      <span className={`px-3 py-1 rounded-full text-xs font-semibold whitespace-nowrap ${getStatusColor(workflow.current_state)}`}>
                        {getStatusLabel(workflow.current_state)}
                      </span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-[var(--bd)] bg-[var(--s1)] p-8 text-center">
              <p className="text-[var(--t3)] mb-4">No active research workflows</p>
              <Link
                href="/research/new"
                className="inline-block px-6 py-2 rounded-lg bg-amber-600 text-white font-medium hover:bg-amber-700 transition-colors"
              >
                Start a New Research
              </Link>
            </div>
          )}
        </div>
      </div>
    </main>
  )
}
