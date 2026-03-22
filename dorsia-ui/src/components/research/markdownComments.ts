export interface MarkdownAnchorComment {
  id: string
  /** Inclusive start index in the raw markdown string */
  start: number
  /** Exclusive end index */
  end: number
  /** Snapshot of selected text when the comment was created */
  quote: string
  body: string
  createdAt: number
}

const PREFIX = 'dorsia-markdown-comments:'

export function loadComments(workflowId: string): MarkdownAnchorComment[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(PREFIX + workflowId)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (x): x is MarkdownAnchorComment =>
        typeof x === 'object' &&
        x !== null &&
        typeof (x as MarkdownAnchorComment).id === 'string' &&
        typeof (x as MarkdownAnchorComment).body === 'string'
    )
  } catch {
    return []
  }
}

export function saveComments(
  workflowId: string,
  comments: MarkdownAnchorComment[]
): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(PREFIX + workflowId, JSON.stringify(comments))
  } catch {
    /* quota / private mode */
  }
}
