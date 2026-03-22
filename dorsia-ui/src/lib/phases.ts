import type { WorkflowState } from '@/lib/types'

export interface WorkflowPhase {
  id: string
  label: string
  states: readonly WorkflowState[]
}

export const WORKFLOW_PHASES: readonly WorkflowPhase[] = [
  {
    id: 'research',
    label: 'Research',
    states: ['INITIATED', 'RESEARCHING', 'RESEARCH_COMPLETE'],
  },
  {
    id: 'review',
    label: 'Agent Review',
    states: [
      'REVIEWING',
      'REVIEW_COMPLETE',
      'RESOLVING',
      'RESOLUTION_COMPLETE',
      'RE_REVIEWING',
      'CONSENSUS_REACHED',
    ],
  },
  {
    id: 'user-review',
    label: 'User Review',
    states: ['USER_REVIEW'],
  },
  {
    id: 'approved',
    label: 'Approved',
    states: ['USER_APPROVED'],
  },
  {
    id: 'final',
    label: 'Final',
    states: ['GENERATING_FINAL', 'COMPLETED'],
  },
] as const

/** Phases for failed/cancelled — map to nearest bucket for display */
const ERROR_STATES: WorkflowState[] = ['FAILED', 'CANCELLED']

export function phaseIndexForState(state: WorkflowState): number {
  if (ERROR_STATES.includes(state)) {
    return -1
  }
  const i = WORKFLOW_PHASES.findIndex((p) =>
    (p.states as readonly string[]).includes(state)
  )
  return i >= 0 ? i : 0
}

export function phaseIdForState(state: WorkflowState): string | null {
  if (ERROR_STATES.includes(state)) return null
  const p = WORKFLOW_PHASES.find((ph) =>
    (ph.states as readonly string[]).includes(state)
  )
  return p?.id ?? null
}

export function phaseContains(phaseId: string, state: WorkflowState): boolean {
  const ph = WORKFLOW_PHASES.find((p) => p.id === phaseId)
  if (!ph) return false
  return (ph.states as readonly string[]).includes(state)
}
