import type { WSEvent } from '@/lib/types'

/**
 * Extract streamed text from research workflow WebSocket events.
 * Backend uses top-level `content`; some gateways may nest under `payload`.
 */
export function getStreamEventText(event: WSEvent): string {
  const top = typeof event.content === 'string' ? event.content : ''
  if (top) return top
  const raw = event as Record<string, unknown>
  const payload = raw.payload as { content?: string } | undefined
  if (payload && typeof payload.content === 'string') return payload.content
  return ''
}
