'use client'
import type { WorkflowState } from '@/lib/types'

interface StatusPillProps {
  state: WorkflowState
}

const stateColors: Record<WorkflowState, { bg: string; text: string }> = {
  INITIATED: { bg: 'bg-slate-500/20', text: 'text-slate-400' },
  RESEARCHING: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
  RESEARCH_COMPLETE: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
  REVIEWING: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
  REVIEW_COMPLETE: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
  RESOLVING: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
  RESOLUTION_COMPLETE: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
  RE_REVIEWING: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
  CONSENSUS_REACHED: { bg: 'bg-amber-500/20', text: 'text-amber-400' },
  USER_REVIEW: { bg: 'bg-amber-500/20', text: 'text-amber-400' },
  USER_APPROVED: { bg: 'bg-green-500/20', text: 'text-green-400' },
  GENERATING_FINAL: { bg: 'bg-green-500/20', text: 'text-green-400' },
  COMPLETED: { bg: 'bg-green-500/20', text: 'text-green-400' },
  FAILED: { bg: 'bg-red-500/20', text: 'text-red-400' },
  CANCELLED: { bg: 'bg-red-500/20', text: 'text-red-400' },
}

const stateLabels: Record<WorkflowState, string> = {
  INITIATED: 'Initiated',
  RESEARCHING: 'Researching',
  RESEARCH_COMPLETE: 'Research Complete',
  REVIEWING: 'Reviewing',
  REVIEW_COMPLETE: 'Review Complete',
  RESOLVING: 'Resolving',
  RESOLUTION_COMPLETE: 'Resolution Complete',
  RE_REVIEWING: 'Re-reviewing',
  CONSENSUS_REACHED: 'Consensus',
  USER_REVIEW: 'Awaiting Review',
  USER_APPROVED: 'Approved',
  GENERATING_FINAL: 'Finalizing',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
}

export function StatusPill({ state }: StatusPillProps) {
  const colors = stateColors[state] || stateColors.INITIATED
  const label = stateLabels[state] || state

  return (
    <span
      className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${colors.bg} ${colors.text}`}
    >
      {label}
    </span>
  )
}
