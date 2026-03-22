export type WorkflowState =
  | 'INITIATED'
  | 'RESEARCHING'
  | 'RESEARCH_COMPLETE'
  | 'REVIEWING'
  | 'REVIEW_COMPLETE'
  | 'RESOLVING'
  | 'RESOLUTION_COMPLETE'
  | 'RE_REVIEWING'
  | 'CONSENSUS_REACHED'
  | 'USER_REVIEW'
  | 'USER_APPROVED'
  | 'GENERATING_FINAL'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

export interface Workflow {
  workflow_id: string
  topic: string
  context: string
  depth: string
  current_state: WorkflowState
  previous_state: WorkflowState | null
  review_cycle: number
  forced_consensus: boolean
  workspace_path: string
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface WorkflowCreateRequest {
  topic: string
  context?: string
  depth?: 'shallow' | 'standard' | 'deep'
  max_review_cycles?: number
  output_format?: string
  agent_config?: Record<string, unknown>
}

export interface WorkflowCreateResponse {
  workflow_id: string
  initial_state: string
  workspace_path: string
}

export interface WorkflowStateDetail {
  workflow_id: string
  current_state: WorkflowState
  previous_state: WorkflowState | null
  review_cycle: number
  forced_consensus: boolean
  state_history: Array<{
    from_state: string
    to_state: string
    trigger: string
    created_at: string
  }>
  active_sessions: string[]
  artifacts: Array<{
    version: string
    file_path: string
    artifact_type: string
    size_bytes: number
    created_at: string
  }>
}

export interface ReviewRound {
  cycle: number
  reviewer_session: string
  consensus: boolean
  overall_quality: number
  summary: string
  comments: ReviewComment[]
  created_at: string
}

export interface ReviewComment {
  id: string
  severity: string
  section: string
  comment: string
  recommendation: string
  resolved: boolean
}

export interface ConversationTurn {
  session_id: string
  role: string
  direction: string
  content: string
  content_type: string
  created_at: string
}

export interface ReportData {
  workflow_id: string
  version: string
  content: string
  is_final?: boolean
}

export interface HealthStatus {
  status: string
  gateway_connected: boolean
  database_ready: boolean
  version: string
}

/** Gateway agent session row (from agent.session WebSocket events). */
export interface AgentSessionRow {
  session_id: string
  flow: string
  role: string
  workspace_dir: string
  process_id: number | null
  status: 'active' | 'ended'
}

export interface WorkspaceFileEntry {
  path: string
  size_bytes: number
}

export interface WorkspaceFilesResponse {
  workflow_id: string
  workspace_path: string
  files: WorkspaceFileEntry[]
}

// WebSocket event types
export type WSEventType =
  | 'connection.state'
  | 'workflow.state_changed'
  | 'agent.stream_start'
  | 'agent.stream_delta'
  | 'agent.stream_end'
  | 'agent.status'
  | 'agent.tool_use'
  | 'agent.session'
  | 'review.comments'
  | 'resolution.merged'
  | 'report.updated'
  | 'workflow.completed'
  | 'workflow.error'
  | 'user.chat_response'
  | 'user.approval_accepted'
  | 'user.changes_accepted'
  | 'error'

export interface WSEvent {
  type: WSEventType
  workflow_id?: string
  data?: Record<string, unknown>
  content?: string
  streaming?: boolean
  [key: string]: unknown
}

// UI state helpers
export const PHASE_GROUPS = {
  researching: ['INITIATED', 'RESEARCHING', 'RESEARCH_COMPLETE'],
  reviewing: ['REVIEWING', 'REVIEW_COMPLETE', 'RESOLVING', 'RESOLUTION_COMPLETE', 'RE_REVIEWING', 'CONSENSUS_REACHED'],
  user_review: ['USER_REVIEW'],
  finalizing: ['USER_APPROVED', 'GENERATING_FINAL'],
  done: ['COMPLETED'],
  error: ['FAILED', 'CANCELLED'],
} as const

export function getPhaseGroup(state: WorkflowState): string {
  for (const [group, states] of Object.entries(PHASE_GROUPS)) {
    if ((states as readonly string[]).includes(state)) return group
  }
  return 'error'
}
