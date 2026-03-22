'use client'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { api } from '@/lib/api'
import { useWorkflowWS } from '@/hooks/useWorkflowWS'
import type { Workflow, ReportData } from '@/lib/types'
import { PhaseStepper } from '@/components/research/PhaseStepper'
import { LiveStream } from '@/components/research/LiveStream'
import { ReviewPanel } from '@/components/research/ReviewPanel'
import { StatusPill } from '@/components/research/StatusPill'
import { AgentSessionPanel } from '@/components/research/AgentSessionPanel'
import { WorkspaceFilesList } from '@/components/research/WorkspaceFilesList'
import { ActivityTimeline } from '@/components/research/ActivityTimeline'
import { AgentEventLog } from '@/components/research/AgentEventLog'
import { UserReviewActions } from '@/components/research/UserReviewActions'
import { ConnectionAlert } from '@/components/research/ConnectionAlert'
import { MarkdownReportViewer } from '@/components/research/MarkdownReportViewer'
import {
  enrichWorkflowEvents,
  streamTextFromEvents,
} from '@/lib/enrichWorkflowEvents'
import { phaseContains } from '@/lib/phases'
import { safeReactText } from '@/lib/safeReactText'

function paramSegment(
  v: string | string[] | undefined
): string | undefined {
  if (v == null) return undefined
  return Array.isArray(v) ? v[0] : v
}

export default function ResearchDetailPage() {
  const params = useParams()
  const workflowId = paramSegment(params.workflowId as string | string[] | undefined)

  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [report, setReport] = useState<ReportData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedPhaseId, setSelectedPhaseId] = useState<string | null>(null)
  const [scrollToEventIndex, setScrollToEventIndex] = useState<number | null>(
    null
  )
  const [linkCopied, setLinkCopied] = useState(false)
  const wsEverConnected = useRef(false)

  const ws = useWorkflowWS(workflowId ?? null)
  const currentState = ws.currentState || workflow?.current_state

  const enrichedEvents = useMemo(
    () =>
      enrichWorkflowEvents(
        ws.events,
        currentState ?? workflow?.current_state ?? null
      ),
    [ws.events, currentState, workflow?.current_state]
  )

  const historicalStreamText = useMemo(
    () =>
      streamTextFromEvents(
        enrichedEvents,
        selectedPhaseId,
        phaseContains
      ),
    [enrichedEvents, selectedPhaseId]
  )

  useEffect(() => {
    if (scrollToEventIndex == null) return
    const t = setTimeout(() => setScrollToEventIndex(null), 2500)
    return () => clearTimeout(t)
  }, [scrollToEventIndex])

  const refetchWorkflow = useCallback(async () => {
    if (!workflowId) return
    try {
      const data = await api.getWorkflow(workflowId)
      setWorkflow(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workflow')
    }
  }, [workflowId])

  // Fetch initial workflow data
  useEffect(() => {
    if (!workflowId) {
      setLoading(false)
      setError('Missing workflow id')
      return
    }
    const run = async () => {
      try {
        const data = await api.getWorkflow(workflowId)
        setWorkflow(data)
        setError(null)
      } catch (err) {
        setError(
          err instanceof Error ? err.message : 'Failed to load workflow'
        )
      } finally {
        setLoading(false)
      }
    }
    run()
  }, [workflowId])

  // When the WebSocket first connects, re-read workflow from API once (WS can be ahead of cached GET).
  // Avoid refetching on every `currentState` change — that caused excessive requests and edge-case races.
  useEffect(() => {
    if (!workflowId) return
    if (ws.connected && !wsEverConnected.current) {
      wsEverConnected.current = true
      void refetchWorkflow()
    }
    if (!ws.connected) {
      wsEverConnected.current = false
    }
  }, [workflowId, ws.connected, refetchWorkflow])

  useEffect(() => {
    if (!workflowId || loading) return
    const id = setInterval(() => {
      refetchWorkflow()
    }, 15000)
    return () => clearInterval(id)
  }, [workflowId, loading, refetchWorkflow])

  // Fetch report when state changes
  useEffect(() => {
    if (!workflowId) return
    if (
      !currentState ||
      ![
        'USER_REVIEW',
        'USER_APPROVED',
        'GENERATING_FINAL',
        'COMPLETED',
      ].includes(currentState)
    ) {
      return
    }

    const fetchReport = async () => {
      try {
        if (currentState === 'COMPLETED') {
          try {
            const data = await api.getFinalReport(workflowId)
            setReport(data)
            return
          } catch {
            /* fall through */
          }
        }
        const data = await api.getReport(workflowId)
        setReport(data)
      } catch (err) {
        console.error('Failed to load report:', err)
      }
    }

    fetchReport()
  }, [currentState, workflowId])

  const copyPageLink = useCallback(async () => {
    if (!workflowId) return
    const url = `${typeof window !== 'undefined' ? window.location.origin : ''}/research/${workflowId}`
    try {
      await navigator.clipboard.writeText(url)
      setLinkCopied(true)
      window.setTimeout(() => setLinkCopied(false), 2000)
    } catch {
      /* ignore */
    }
  }, [workflowId])

  if (loading) {
    return (
      <div className="flex min-h-[50vh] w-full items-center justify-center px-4 text-[var(--t1)]">
        <div className="text-center">
          <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-4 border-[var(--a5)] border-t-transparent" />
          <p className="text-sm text-[var(--t2)]">Loading workflow…</p>
        </div>
      </div>
    )
  }

  if (error || !workflow || !workflowId) {
    return (
      <div className="w-full px-4 py-10 text-[var(--t1)]">
        <div className="max-w-4xl mx-auto px-4 py-8">
          <div className="p-6 bg-red-500/10 text-red-400 rounded border border-red-500/30">
            {error || 'Workflow not found'}
          </div>
        </div>
      </div>
    )
  }

  const state = currentState || workflow.current_state
  const isInProgress = [
    'INITIATED',
    'RESEARCHING',
    'RESEARCH_COMPLETE',
    'REVIEWING',
    'REVIEW_COMPLETE',
    'RESOLVING',
    'RESOLUTION_COMPLETE',
    'RE_REVIEWING',
    'CONSENSUS_REACHED',
    'USER_APPROVED',
    'GENERATING_FINAL',
  ].includes(state)
  const isUserReview = state === 'USER_REVIEW'
  const isCompleted = state === 'COMPLETED'
  const isFailed = ['FAILED', 'CANCELLED'].includes(state)

  const wsLabel = ws.connected
    ? 'live'
    : ws.reconnecting
      ? '…'
      : ws.permanentClose
        ? 'err'
        : 'off'

  const workflowDetailPath = `/research/${workflowId}`

  const activeAgentLabel =
    state === 'RESEARCHING' || state === 'INITIATED'
      ? 'Researcher'
      : state === 'REVIEWING' ||
          state === 'REVIEW_COMPLETE' ||
          state === 'RE_REVIEWING'
        ? 'Reviewer'
        : state === 'RESOLVING' || state === 'RESOLUTION_COMPLETE'
          ? 'Resolver'
          : state === 'USER_APPROVED' || state === 'GENERATING_FINAL'
            ? 'Final report'
            : 'Agent'

  return (
    <div className="wf-grid mx-auto w-full max-w-[1600px] px-2 py-2 pb-16 text-[var(--t1)] sm:px-3">
      {/* —— Row: workflow title | status | id —— */}
      <header className="ds-surface ds-tight col-span-12 grid grid-cols-12 gap-x-2 gap-y-2 p-2 sm:p-2.5">
        <div className="col-span-12 min-w-0 sm:col-span-6 lg:col-span-5">
          <p className="text-[9px] font-semibold uppercase tracking-wide text-[var(--t4)]">
            Workflow
          </p>
          <div className="mt-0.5 flex flex-wrap items-start gap-x-2 gap-y-1">
            <h1 className="line-clamp-2 min-w-0 flex-1 text-sm font-semibold leading-tight sm:text-base">
              <Link
                href={workflowDetailPath}
                className="text-[var(--t1)] hover:text-[var(--a5)] hover:underline"
                title="Open this workflow (⌘/Ctrl+click for new tab)"
              >
                {safeReactText(workflow.topic)}
              </Link>
            </h1>
            <div className="flex shrink-0 flex-wrap items-center gap-1.5 text-[10px]">
              <Link
                href="/research"
                className="rounded border border-white/10 px-1.5 py-0.5 text-[var(--t3)] hover:border-white/20 hover:text-[var(--t1)]"
              >
                List
              </Link>
              <a
                href={workflowDetailPath}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded border border-white/10 px-1.5 py-0.5 text-[var(--t3)] hover:border-white/20 hover:text-[var(--t1)]"
              >
                Open
              </a>
              <button
                type="button"
                onClick={copyPageLink}
                className="rounded border border-white/10 px-1.5 py-0.5 text-[var(--t3)] hover:border-white/20 hover:text-[var(--t1)]"
              >
                {linkCopied ? 'Copied' : 'Copy link'}
              </button>
            </div>
          </div>
          <p className="mt-0.5 text-[10px] text-[var(--t3)]">
            C{workflow.review_cycle} · {workflow.depth}
          </p>
        </div>
        <div className="col-span-12 flex flex-wrap items-center gap-1.5 sm:col-span-6 sm:justify-end lg:col-span-4">
          <StatusPill state={state} />
          <span
            className="rounded border border-white/10 bg-black/30 px-1.5 py-0.5 font-mono text-[9px] text-[var(--t3)]"
            title="UI WebSocket"
          >
            ws:{wsLabel}
          </span>
        </div>
        <div className="col-span-12 font-mono text-[9px] text-[var(--t4)] lg:col-span-3 lg:text-right">
          {workflow.workflow_id}
        </div>

        <div className="col-span-12 border-t border-white/[0.06] pt-2">
          <ActivityTimeline
            compact
            enriched={enrichedEvents}
            onSelectIndex={(i) => {
              setSelectedPhaseId(null)
              setScrollToEventIndex(i)
            }}
          />
        </div>

        <div className="col-span-12 border-t border-white/[0.06] pt-2">
          <p className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-[var(--t4)]">
            Phases
          </p>
          <PhaseStepper
            compact
            currentState={state}
            selectedPhaseId={selectedPhaseId}
            onPhaseSelect={(id) => {
              setScrollToEventIndex(null)
              setSelectedPhaseId(id)
            }}
          />
          {selectedPhaseId !== null && (
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px] text-[var(--t2)]">
              <span>Phase history</span>
              <button
                type="button"
                onClick={() => setSelectedPhaseId(null)}
                className="font-medium text-amber-400/90 hover:underline"
              >
                Live
              </button>
            </div>
          )}
        </div>
      </header>

      <div className="col-span-12">
        <ConnectionAlert
          connected={ws.connected}
          reconnecting={ws.reconnecting}
          permanentClose={ws.permanentClose}
          permanentMessage={ws.permanentMessage}
          onRetry={ws.reconnect}
        />
      </div>

      {isUserReview ? (
        <>
          <section className="ds-surface ds-tight col-span-12 flex max-h-[min(78vh,800px)] min-h-[18rem] flex-col overflow-hidden sm:min-h-[20rem] lg:col-span-6">
            <div className="border-b border-white/[0.06] px-2 py-1.5 sm:px-3">
              <h2 className="text-xs font-medium">Draft report</h2>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2 sm:p-3">
              {report ? (
                <MarkdownReportViewer
                  workflowId={workflowId}
                  markdown={String(report.content ?? '')}
                />
              ) : (
                <div className="py-8 text-center text-[var(--t3)]">
                  Loading…
                </div>
              )}
            </div>
          </section>
          <section className="ds-surface ds-tight col-span-12 flex max-h-[min(78vh,800px)] min-h-[18rem] flex-col overflow-hidden sm:min-h-[20rem] lg:col-span-6">
            <div className="border-b border-white/[0.06] px-2 py-1.5 sm:px-3">
              <h2 className="text-xs font-medium">Review chat</h2>
            </div>
            <div className="min-h-0 flex-1">
              <ReviewPanel
                workflowId={workflowId}
                onSendMessage={ws.sendMessage}
                streamingReply={ws.chatStreamChunks.join('')}
              />
            </div>
          </section>
          <div className="col-span-12">
            <UserReviewActions
              workflowId={workflowId}
              onDone={refetchWorkflow}
            />
          </div>
        </>
      ) : (
        <>
          {isInProgress && (
            <>
              <section className="ds-surface ds-tight col-span-12 flex max-h-[min(78vh,820px)] min-h-[14rem] flex-col overflow-hidden lg:col-span-5">
                <div className="border-b border-white/[0.06] px-2 py-1.5">
                  <h2 className="text-xs font-medium">Agent output</h2>
                  {selectedPhaseId !== null && (
                    <p className="text-[10px] text-[var(--t3)]">Replay</p>
                  )}
                </div>
                <div className="min-h-0 flex-1 p-1.5">
                  <LiveStream
                    historyMode={selectedPhaseId !== null}
                    {...(selectedPhaseId !== null
                      ? { text: historicalStreamText }
                      : { chunks: ws.agentStreamChunks })}
                    activeAgent={activeAgentLabel}
                  />
                </div>
              </section>

              <div className="ds-surface ds-tight col-span-12 flex max-h-[min(78vh,820px)] min-h-[14rem] flex-col overflow-hidden lg:col-span-4">
                <AgentEventLog
                  enriched={enrichedEvents}
                  phaseFilterId={selectedPhaseId}
                  phaseContains={phaseContains}
                  scrollToIndex={scrollToEventIndex}
                />
              </div>

              <aside className="col-span-12 flex max-h-[min(78vh,820px)] flex-col gap-2 lg:col-span-3">
                <div className="ds-surface ds-tight px-2 py-1.5 text-[10px] text-[var(--t2)]">
                  <span className="text-[var(--t3)]">State</span>{' '}
                  <span className="font-medium text-[var(--t1)]">{state}</span>
                  <span className="mx-1 text-[var(--bd)]">·</span>
                  <span className="text-[var(--t3)]">WS</span>{' '}
                  {ws.connected ? (
                    <span className="text-emerald-400">ok</span>
                  ) : ws.reconnecting ? (
                    <span className="text-amber-400">…</span>
                  ) : ws.permanentClose ? (
                    <span className="text-red-400">!</span>
                  ) : (
                    <span className="text-red-400">×</span>
                  )}
                </div>
                <div className="ds-surface ds-tight flex min-h-0 min-h-[7rem] flex-1 flex-col overflow-hidden p-2">
                  <h3 className="mb-1 text-[10px] font-medium uppercase tracking-wide text-[var(--t4)]">
                    Gateway
                  </h3>
                  <div className="min-h-0 flex-1 overflow-y-auto">
                    <AgentSessionPanel sessions={ws.agentSessions} />
                  </div>
                </div>
                <div className="ds-surface ds-tight flex min-h-[7rem] flex-1 flex-col overflow-hidden p-2">
                  <h3 className="mb-1 text-[10px] font-medium uppercase tracking-wide text-[var(--t4)]">
                    Files
                  </h3>
                  <div className="min-h-0 flex-1 overflow-y-auto">
                    <WorkspaceFilesList workflowId={workflowId} />
                  </div>
                </div>
              </aside>
            </>
          )}

          {isCompleted && (
            <div className="ds-surface ds-tight col-span-12 p-3 sm:p-4">
              <div className="mb-2 inline-flex items-center gap-1.5 rounded bg-green-500/20 px-2 py-1 text-xs text-green-400">
                <svg
                  className="h-3.5 w-3.5"
                  fill="currentColor"
                  viewBox="0 0 20 20"
                >
                  <path
                    fillRule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                    clipRule="evenodd"
                  />
                </svg>
                <span className="font-medium">Completed</span>
              </div>

              <h2 className="mb-2 text-sm font-bold">Final report</h2>

              {report ? (
                <div className="mb-3 max-h-[min(55vh,28rem)] overflow-y-auto rounded bg-[var(--bg)] p-2">
                  <MarkdownReportViewer
                    workflowId={workflowId}
                    markdown={String(report.content ?? '')}
                  />
                </div>
              ) : (
                <div className="py-4 text-center text-[var(--t3)]">
                  Loading…
                </div>
              )}

              <button
                type="button"
                onClick={() => {
                  if (report?.content != null) {
                    const blob = new Blob([String(report.content)], {
                      type: 'text/plain',
                    })
                    const url = URL.createObjectURL(blob)
                    const a = document.createElement('a')
                    a.href = url
                    a.download = `research-${workflowId}.txt`
                    a.click()
                  }
                }}
                className="rounded bg-[var(--a5)] px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-[var(--a4)]"
              >
                Download
              </button>
            </div>
          )}

          {isFailed && (
            <div className="ds-surface ds-tight col-span-12 border-red-500/25 p-3 sm:p-4">
              <div className="mb-2 inline-flex items-center gap-1.5 rounded bg-red-500/20 px-2 py-1 text-xs text-red-400">
                <svg
                  className="h-3.5 w-3.5"
                  fill="currentColor"
                  viewBox="0 0 20 20"
                >
                  <path
                    fillRule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                    clipRule="evenodd"
                  />
                </svg>
                <span className="font-medium">{state}</span>
              </div>
              <p className="text-xs text-[var(--t2)]">
                The workflow was {state.toLowerCase()}.
              </p>
            </div>
          )}

          {!isInProgress && (
            <div className="col-span-12">
              <h3 className="mb-1 text-[10px] font-medium uppercase tracking-wide text-[var(--t4)]">
                All events
              </h3>
              <div className="ds-surface ds-tight max-h-[min(65vh,26rem)] min-h-[10rem] overflow-hidden">
                <AgentEventLog
                  enriched={enrichedEvents}
                  phaseFilterId={selectedPhaseId}
                  phaseContains={phaseContains}
                  scrollToIndex={scrollToEventIndex}
                />
              </div>
            </div>
          )}

          {!isInProgress && (
            <div className="col-span-12 grid grid-cols-12 gap-2">
              <div className="ds-surface ds-tight col-span-12 p-2 md:col-span-6">
                <h3 className="mb-1 text-[10px] font-medium uppercase text-[var(--t4)]">
                  Gateway
                </h3>
                <div className="max-h-[min(40vh,16rem)] overflow-y-auto">
                  <AgentSessionPanel sessions={ws.agentSessions} />
                </div>
              </div>
              <div className="ds-surface ds-tight col-span-12 p-2 md:col-span-6">
                <h3 className="mb-1 text-[10px] font-medium uppercase text-[var(--t4)]">
                  Files
                </h3>
                <div className="max-h-[min(40vh,16rem)] overflow-y-auto">
                  <WorkspaceFilesList workflowId={workflowId} />
                </div>
              </div>
            </div>
          )}

          <div className="col-span-12 grid grid-cols-12 gap-2">
            <div className="ds-surface ds-tight col-span-12 p-2 sm:col-span-4">
              <div className="mb-0.5 text-[9px] text-[var(--t3)]">Created</div>
              <div className="text-[11px] font-medium">
                {new Date(workflow.created_at).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </div>
            </div>
            <div className="ds-surface ds-tight col-span-12 p-2 sm:col-span-4">
              <div className="mb-0.5 text-[9px] text-[var(--t3)]">Updated</div>
              <div className="text-[11px] font-medium">
                {new Date(workflow.updated_at).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </div>
            </div>
            <div className="ds-surface ds-tight col-span-12 p-2 sm:col-span-4">
              <div className="mb-0.5 text-[9px] text-[var(--t3)]">Workspace</div>
              <div className="break-words font-mono text-[9px] text-[var(--t1)]">
                {safeReactText(workflow.workspace_path)}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
