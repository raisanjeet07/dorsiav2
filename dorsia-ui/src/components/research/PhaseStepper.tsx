'use client'

import type { WorkflowState } from '@/lib/types'
import { WORKFLOW_PHASES } from '@/lib/phases'

interface PhaseStepperProps {
  currentState: WorkflowState
  /** When set, user is reviewing a completed phase (not live). */
  selectedPhaseId?: string | null
  onPhaseSelect?: (phaseId: string | null) => void
  /** Smaller controls to fit workflow header on one row (scrolls horizontally). */
  compact?: boolean
}

export function PhaseStepper({
  currentState,
  selectedPhaseId = null,
  onPhaseSelect,
  compact = false,
}: PhaseStepperProps) {
  const currentPhaseIndex = WORKFLOW_PHASES.findIndex((p) =>
    (p.states as readonly string[]).includes(currentState)
  )
  const unknownState = currentPhaseIndex < 0

  return (
    <div
      className={
        compact
          ? 'flex flex-nowrap items-center gap-x-0.5 overflow-x-auto pb-0.5 sm:gap-1'
          : 'flex flex-wrap items-center gap-y-2 gap-x-1 sm:gap-2 overflow-x-auto pb-2'
      }
    >
      {WORKFLOW_PHASES.map((phase, index) => {
        const isDone =
          !unknownState && currentPhaseIndex >= 0 && index < currentPhaseIndex
        const isActive =
          !unknownState && currentPhaseIndex >= 0 && index === currentPhaseIndex
        const isFuture =
          unknownState ||
          (currentPhaseIndex >= 0 && index > currentPhaseIndex)
        const isSelected = selectedPhaseId === phase.id
        const clickable = (isDone || isActive) && onPhaseSelect

        return (
          <div
            key={phase.id}
            className={`flex items-center ${compact ? 'gap-0.5' : 'gap-1 sm:gap-2'}`}
          >
            <button
              type="button"
              disabled={!clickable || isFuture}
              onClick={() => {
                if (!onPhaseSelect) return
                if (isDone) onPhaseSelect(phase.id)
                if (isActive) onPhaseSelect(null)
              }}
              className={[
                compact
                  ? 'flex items-center gap-1 rounded-md px-1 py-0.5 transition-colors text-left'
                  : 'flex items-center gap-2 rounded-lg px-1 py-1 sm:px-2 transition-colors text-left',
                clickable && !isFuture
                  ? 'cursor-pointer hover:bg-[var(--s2)]'
                  : 'cursor-default',
                isFuture ? 'opacity-45' : '',
                isSelected ? 'ring-2 ring-[var(--a5)] ring-offset-2 ring-offset-[var(--bg-2)]' : '',
              ].join(' ')}
              title={
                isDone
                  ? `View activity for ${phase.label}`
                  : isActive
                    ? 'Back to live (current phase)'
                    : undefined
              }
            >
              <div
                className={`relative flex flex-shrink-0 items-center justify-center rounded-full ${
                  compact ? 'h-4 w-4' : 'h-6 w-6'
                }`}
              >
                {isDone && (
                  <div
                    className={`flex items-center justify-center rounded-full bg-green-500 ${
                      compact ? 'h-4 w-4' : 'h-6 w-6'
                    }`}
                  >
                    <svg
                      className={`text-white ${compact ? 'h-2.5 w-2.5' : 'h-4 w-4'}`}
                      fill="currentColor"
                      viewBox="0 0 20 20"
                    >
                      <path
                        fillRule="evenodd"
                        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                        clipRule="evenodd"
                      />
                    </svg>
                  </div>
                )}
                {isActive && (
                  <div
                    className={`flex animate-pulse items-center justify-center rounded-full bg-[var(--a5)] ${
                      compact ? 'h-4 w-4' : 'h-6 w-6'
                    }`}
                  >
                    <div
                      className={`rounded-full bg-[var(--a3)] ${
                        compact ? 'h-1 w-1' : 'h-2 w-2'
                      }`}
                    />
                  </div>
                )}
                {isFuture && (
                  <div
                    className={`rounded-full bg-[var(--s4)] ${
                      compact ? 'h-4 w-4' : 'h-6 w-6'
                    }`}
                  />
                )}
              </div>

              <span
                className={`font-medium whitespace-nowrap ${
                  compact ? 'max-w-[4.5rem] truncate text-[10px] sm:max-w-none' : 'text-sm'
                } ${
                  isDone
                    ? 'text-green-400'
                    : isActive
                      ? 'text-[var(--a5)]'
                      : 'text-[var(--t3)]'
                }`}
              >
                {phase.label}
              </span>
            </button>

            {index < WORKFLOW_PHASES.length - 1 && (
              <div className={`flex-shrink-0 ${compact ? 'block' : 'hidden sm:block'}`}>
                <svg
                  className={`${compact ? 'h-3 w-3' : 'w-5 h-5'} ${
                    isDone ? 'text-green-500' : 'text-[var(--t4)]'
                  }`}
                  fill="currentColor"
                  viewBox="0 0 20 20"
                >
                  <path
                    fillRule="evenodd"
                    d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"
                    clipRule="evenodd"
                  />
                </svg>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
