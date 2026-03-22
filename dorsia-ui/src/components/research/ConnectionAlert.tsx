'use client'

import { useEffect, useState } from 'react'
import { getWsBaseUrl } from '@/lib/wsUrl'
import { getApiBaseUrl } from '@/lib/api'

/**
 * Explains WebSocket status: transient reconnects (amber) vs permanent server refusal (red).
 */
export function ConnectionAlert(props: {
  connected: boolean
  reconnecting: boolean
  permanentClose: boolean
  permanentMessage: string | null
  onRetry?: () => void
}) {
  const {
    connected,
    reconnecting,
    permanentClose,
    permanentMessage,
    onRetry,
  } = props
  const [slow, setSlow] = useState(false)

  const wsBase = getWsBaseUrl()
  const httpsUiBlocksWs =
    typeof window !== 'undefined' &&
    window.location.protocol === 'https:' &&
    wsBase.startsWith('ws://')

  useEffect(() => {
    if (connected || permanentClose) {
      setSlow(false)
      return
    }
    const t = window.setTimeout(() => setSlow(true), 4000)
    return () => window.clearTimeout(t)
  }, [connected, permanentClose])

  if (connected && !permanentClose) return null

  if (permanentClose) {
    return (
      <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-[11px] text-red-200 sm:text-xs">
        <p className="font-medium text-red-100">Live updates unavailable</p>
        <p className="mt-1 text-red-200/90">
          {permanentMessage ||
            'The server closed the WebSocket (e.g. workflow missing in the database).'}
        </p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 rounded bg-red-500/30 px-2 py-1 text-[11px] font-medium text-red-100 hover:bg-red-500/40"
          >
            Retry connection
          </button>
        )}
        <p className="mt-2 font-mono text-[10px] text-red-300/80">
          REST: {getApiBaseUrl()} · WS: {wsBase}
        </p>
      </div>
    )
  }

  if (httpsUiBlocksWs) {
    return (
      <div className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100 sm:text-xs">
        <p className="font-medium">WebSocket may be blocked (mixed content)</p>
        <p className="mt-1 text-amber-200/90">
          This page is loaded over <strong>HTTPS</strong> but the API WebSocket is{' '}
          <strong>ws://</strong> (not encrypted). Browsers block that. Use{' '}
          <strong>http://</strong> for local UI, or serve the API with{' '}
          <strong>wss://</strong> and set <code className="rounded bg-black/30 px-1">NEXT_PUBLIC_WS_URL</code>{' '}
          / <code className="rounded bg-black/30 px-1">NEXT_PUBLIC_API_URL</code> accordingly.
        </p>
        <p className="mt-1 font-mono text-[10px] text-amber-200/70">
          Page: {typeof window !== 'undefined' ? window.location.origin : ''} · WS: {wsBase}
        </p>
      </div>
    )
  }

  if (reconnecting || slow) {
    return (
      <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100 sm:text-xs">
        <p className="font-medium">Connecting to live workflow stream…</p>
        <p className="mt-1 text-amber-200/80">
          {reconnecting
            ? 'Will keep retrying with backoff while the research API is reachable.'
            : 'Still waiting for the first message from the server.'}
        </p>
        <p className="mt-1 font-mono text-[10px] text-amber-200/60">
          REST: {getApiBaseUrl()} · WS: {wsBase}
        </p>
      </div>
    )
  }

  return null
}
