'use client'
import { useEffect, useRef, useState, useCallback } from 'react'
import type { WSEvent, WorkflowState, AgentSessionRow } from '@/lib/types'
import { getStreamEventText } from '@/lib/eventContent'
import { getWorkflowWebSocketUrl } from '@/lib/wsUrl'

/** Parse JSON frames from the research API; coerce `type` so we never drop valid events. */
function parseWsEvent(raw: string): WSEvent | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    if (process.env.NODE_ENV === 'development') {
      console.warn('[useWorkflowWS] non-JSON WebSocket frame', raw.slice(0, 200))
    }
    return null
  }
  if (parsed == null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return null
  }
  const obj = parsed as Record<string, unknown>
  if (!('type' in obj)) {
    return null
  }
  const t = obj.type
  const typeStr = typeof t === 'string' ? t : String(t)
  return { ...obj, type: typeStr } as WSEvent
}

/** Exponential backoff capped at 30s — never give up on transient network / server restarts. */
const MAX_DELAY_MS = 30_000
function reconnectDelayMs(attemptIndex: number): number {
  const ms = Math.min(1000 * 2 ** attemptIndex, MAX_DELAY_MS)
  return ms
}

/** Don't retry — server rejected this workflow (e.g. not in DB). */
const NO_RETRY_CODES = new Set([1008, 1003])

interface WSState {
  connected: boolean
  /** True while socket not OPEN (initial connect or scheduled reconnect). */
  reconnecting: boolean
  /** Server closed with a code we should not retry (e.g. 1008 workflow not found). */
  permanentClose: boolean
  permanentMessage: string | null
  currentState: WorkflowState | null
  events: WSEvent[]
  /** Agent phases only (research / review / resolve / final) — not user chat */
  agentStreamChunks: string[]
  /** USER_REVIEW chat assistant output only */
  chatStreamChunks: string[]
  agentSessions: AgentSessionRow[]
}

const initialState = (): WSState => ({
  connected: false,
  reconnecting: true,
  permanentClose: false,
  permanentMessage: null,
  currentState: null,
  events: [],
  agentStreamChunks: [],
  chatStreamChunks: [],
  agentSessions: [],
})

function mergeAgentSession(
  list: AgentSessionRow[],
  row: AgentSessionRow
): AgentSessionRow[] {
  const next = [...list]
  const idx = next.findIndex(
    (x) => x.session_id === row.session_id && x.flow === row.flow
  )
  if (idx >= 0) next[idx] = { ...next[idx], ...row }
  else next.push(row)
  return next
}

export function useWorkflowWS(workflowId: string | null) {
  const [state, setState] = useState<WSState>(initialState)
  const wsRef = useRef<WebSocket | null>(null)
  const attemptRef = useRef(0)
  const intentionalCloseRef = useRef(false)
  const reconnectTimerRef = useRef<number | null>(null)
  const [reconnectNonce, setReconnectNonce] = useState(0)

  useEffect(() => {
    if (!workflowId) return

    intentionalCloseRef.current = false
    setState(initialState())
    attemptRef.current = 0

    const scheduleReconnect = () => {
      if (intentionalCloseRef.current) return
      const delay = reconnectDelayMs(attemptRef.current)
      setState((s) => ({ ...s, reconnecting: true, connected: false }))
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null
        if (intentionalCloseRef.current) return
        attemptRef.current += 1
        connect()
      }, delay)
    }

    const connect = () => {
      if (intentionalCloseRef.current) return
      setState((s) => ({
        ...s,
        reconnecting: true,
        connected: false,
        permanentClose: false,
        permanentMessage: null,
      }))

      const ws = new WebSocket(getWorkflowWebSocketUrl(workflowId))
      wsRef.current = ws

      ws.onopen = () => {
        attemptRef.current = 0
        setState((s) => ({
          ...s,
          connected: true,
          reconnecting: false,
          permanentClose: false,
          permanentMessage: null,
        }))
      }

      ws.onmessage = (e) => {
        try {
          const event = parseWsEvent(
            typeof e.data === 'string' ? e.data : String(e.data)
          )
          if (!event) return

          setState((s) => {
            const newState = { ...s }
            newState.events = [...s.events.slice(-500), event]

            if (event.type === 'connection.state' && event.data) {
              newState.currentState = (event.data as { current_state?: WorkflowState })
                .current_state as WorkflowState
            }
            if (event.type === 'workflow.state_changed') {
              const w = event as {
                to_state?: WorkflowState
                data?: { to_state?: WorkflowState; current_state?: WorkflowState }
              }
              const next =
                (w.to_state ||
                  w.data?.to_state ||
                  w.data?.current_state) as WorkflowState
              newState.currentState = next
            }

            const text = getStreamEventText(event)
            const role = (event as { role?: string }).role
            if (event.type === 'agent.stream_delta' && text) {
              if (role === 'user-chat') {
                newState.chatStreamChunks = [
                  ...s.chatStreamChunks.slice(-500),
                  text,
                ]
              } else {
                newState.agentStreamChunks = [
                  ...s.agentStreamChunks.slice(-500),
                  text,
                ]
              }
            }
            if (event.type === 'user.chat_response' && text) {
              newState.chatStreamChunks = [
                ...s.chatStreamChunks.slice(-500),
                text,
              ]
            }

            if (event.type === 'agent.session') {
              const row: AgentSessionRow = {
                session_id: String((event as { session_id?: string }).session_id ?? ''),
                flow: String((event as { flow?: string }).flow ?? ''),
                role: String((event as { role?: string }).role ?? ''),
                workspace_dir: String(
                  (event as { workspace_dir?: string }).workspace_dir ?? ''
                ),
                process_id:
                  (event as { process_id?: number | null }).process_id ?? null,
                status: ((event as { status?: string }).status === 'ended'
                  ? 'ended'
                  : 'active') as AgentSessionRow['status'],
              }
              if (row.session_id && row.flow) {
                newState.agentSessions = mergeAgentSession(
                  s.agentSessions,
                  row
                )
              }
            }
            return newState
          })
        } catch {
          /* ignore malformed */
        }
      }

      ws.onclose = (ev: CloseEvent) => {
        setState((s) => ({ ...s, connected: false }))
        if (intentionalCloseRef.current) return

        if (NO_RETRY_CODES.has(ev.code)) {
          setState((s) => ({
            ...s,
            reconnecting: false,
            permanentClose: true,
            permanentMessage:
              ev.reason?.trim() ||
              (ev.code === 1008
                ? 'Workflow not found or access denied'
                : 'WebSocket closed by server'),
          }))
          return
        }

        scheduleReconnect()
      }

      ws.onerror = () => {
        try {
          ws.close()
        } catch {
          /* ignore */
        }
      }
    }

    connect()

    return () => {
      intentionalCloseRef.current = true
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [workflowId, reconnectNonce])

  const reconnect = useCallback(() => {
    setState((s) => ({
      ...s,
      permanentClose: false,
      permanentMessage: null,
      reconnecting: true,
    }))
    attemptRef.current = 0
    setReconnectNonce((n) => n + 1)
  }, [])

  const send = useCallback((data: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  const sendMessage = useCallback(
    (message: string) => {
      setState((s) => ({ ...s, chatStreamChunks: [] }))
      send({ type: 'user.message', payload: { message } })
    },
    [send]
  )

  const sendApprove = useCallback(
    (comment?: string) => {
      send({ type: 'user.approve', payload: { comment: comment || '' } })
    },
    [send]
  )

  const sendRequestChanges = useCallback(
    (changes: Record<string, unknown>) => {
      send({
        type: 'user.request_changes',
        payload: { changes },
      })
    },
    [send]
  )

  const sendCancel = useCallback(() => {
    send({ type: 'user.cancel', payload: {} })
  }, [send])

  return {
    ...state,
    /** @deprecated use agentStreamChunks */
    streamChunks: state.agentStreamChunks,
    /** True after repeated failures (removed) — use permanentClose */
    failed: state.permanentClose,
    send,
    sendMessage,
    sendApprove,
    sendRequestChanges,
    sendCancel,
    reconnect,
  }
}

