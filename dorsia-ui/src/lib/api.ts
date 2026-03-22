import type {
  Workflow,
  WorkflowCreateRequest,
  WorkflowCreateResponse,
  WorkflowStateDetail,
  HealthStatus,
  ReportData,
  ReviewRound,
  ConversationTurn,
  WorkspaceFilesResponse,
} from './types'

const DEFAULT_TIMEOUT_MS = 60_000

export const getApiBaseUrl = (): string =>
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const BASE = `${getApiBaseUrl()}/api/v1`

function parseErrorDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        if (typeof e === 'object' && e && 'msg' in e) {
          return String((e as { msg: string }).msg)
        }
        return String(e)
      })
      .join(', ')
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: string }).message)
  }
  return 'Request failed'
}

async function request<T>(
  path: string,
  options?: RequestInit & { timeoutMs?: number }
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...init } = options ?? {}
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json', ...init?.headers },
      ...init,
      signal: controller.signal,
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      const detail =
        (body as { detail?: unknown }).detail ?? res.statusText
      throw new Error(parseErrorDetail(detail) || `HTTP ${res.status}`)
    }
    try {
      return (await res.json()) as T
    } catch {
      throw new Error(
        `Expected JSON from ${BASE}${path} — got non-JSON body. Check NEXT_PUBLIC_API_URL points at the research API (e.g. http://localhost:8000).`
      )
    }
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') {
      throw new Error('Request timed out — is the research API running?')
    }
    throw e
  } finally {
    clearTimeout(timer)
  }
}

export const api = {
  // Health
  health: () => request<HealthStatus>('/health', { timeoutMs: 10_000 }),

  // Workflows
  createWorkflow: (data: WorkflowCreateRequest) =>
    request<WorkflowCreateResponse>('/workflows', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  listWorkflows: async (params?: {
    state?: string
    limit?: number
    offset?: number
  }) => {
    const qs = new URLSearchParams()
    if (params?.state) qs.set('state', params.state)
    if (params?.limit) qs.set('limit', String(params.limit))
    if (params?.offset) qs.set('offset', String(params.offset))
    const query = qs.toString() ? `?${qs}` : ''
    const data = await request<{
      workflows?: Workflow[]
      total?: number
      limit?: number
      offset?: number
    }>(`/workflows${query}`)
    const workflows = Array.isArray(data.workflows) ? data.workflows : []
    return {
      workflows,
      total: data.total ?? workflows.length,
      limit: data.limit ?? params?.limit ?? 100,
      offset: data.offset ?? params?.offset ?? 0,
    }
  },

  getWorkflow: (id: string) => request<Workflow>(`/workflows/${id}`),

  getWorkflowState: (id: string) =>
    request<WorkflowStateDetail>(`/workflows/${id}/state`),

  /** Files on disk for this workflow only (research service workspace). */
  listWorkspaceFiles: (id: string) =>
    request<WorkspaceFilesResponse>(`/workflows/${id}/workspace-files`),

  cancelWorkflow: (id: string) =>
    request<Record<string, unknown>>(`/workflows/${id}/cancel`, {
      method: 'POST',
    }),

  // Reports
  getReport: (id: string) =>
    request<ReportData>(`/workflows/${id}/report`),

  getFinalReport: (id: string) =>
    request<
      ReportData & { file_path: string; download_url: string }
    >(`/workflows/${id}/report/final`),

  // Reviews
  getReviews: (id: string) =>
    request<{
      workflow_id: string
      reviews: ReviewRound[]
      total_cycles: number
    }>(`/workflows/${id}/reviews`),

  // Conversations
  getConversations: (id: string, role?: string) => {
    const qs = role ? `?role=${role}` : ''
    return request<{
      workflow_id: string
      conversations: ConversationTurn[]
      total: number
    }>(`/workflows/${id}/conversations${qs}`)
  },

  // User Actions
  approveWorkflow: (id: string, comment?: string) =>
    request<Record<string, unknown>>(`/workflows/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ comment: comment || '' }),
    }),

  requestChanges: (id: string, changes: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/workflows/${id}/request-changes`, {
      method: 'POST',
      body: JSON.stringify({ changes }),
    }),
}
