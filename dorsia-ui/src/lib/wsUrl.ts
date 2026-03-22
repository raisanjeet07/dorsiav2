/**
 * Base URL for browser → research API WebSocket (`/ws/workflows/...`).
 *
 * If `NEXT_PUBLIC_WS_URL` is unset, derive from `NEXT_PUBLIC_API_URL` so a single
 * env (e.g. `http://192.168.x.x:8000`) fixes both REST and WS without a second variable.
 */
export function getWsBaseUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_WS_URL
  if (explicit != null && String(explicit).trim() !== '') {
    return String(explicit).replace(/\/$/, '')
  }

  const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
  try {
    const u = new URL(api)
    const proto = u.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${u.host}`
  } catch {
    return 'ws://localhost:8000'
  }
}

export function getWorkflowWebSocketUrl(workflowId: string): string {
  const base = getWsBaseUrl()
  const id = encodeURIComponent(workflowId)
  return `${base}/ws/workflows/${id}`
}
