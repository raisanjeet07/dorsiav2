'use client'

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  loadComments,
  saveComments,
  type MarkdownAnchorComment,
} from './markdownComments'

type Tab = 'preview' | 'annotate'

function newId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return `c-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

interface MarkdownReportViewerProps {
  workflowId: string
  markdown: string
}

/**
 * Rendered markdown preview + source annotate mode with selection-scoped comments (localStorage).
 */
export function MarkdownReportViewer({
  workflowId,
  markdown,
}: MarkdownReportViewerProps) {
  const [tab, setTab] = useState<Tab>('preview')
  const [comments, setComments] = useState<MarkdownAnchorComment[]>([])
  const [draftBody, setDraftBody] = useState('')
  /** Bump so disabled/enabled on selection updates re-render */
  const [selVersion, setSelVersion] = useState(0)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const gutterRef = useRef<HTMLDivElement>(null)
  const previewRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setComments(loadComments(workflowId))
  }, [workflowId])

  useEffect(() => {
    saveComments(workflowId, comments)
  }, [workflowId, comments])

  const lines = useMemo(() => markdown.split('\n'), [markdown])
  const lineCount = lines.length

  const syncScroll = () => {
    const ta = taRef.current
    const g = gutterRef.current
    if (ta && g) g.scrollTop = ta.scrollTop
  }

  const selectionRangeInTextarea = useCallback(() => {
    const ta = taRef.current
    if (!ta) return null
    const start = ta.selectionStart
    const end = ta.selectionEnd
    if (start === end) return null
    return {
      start,
      end,
      quote: markdown.slice(start, end),
    }
  }, [markdown])

  const addCommentFromTextarea = () => {
    const r = selectionRangeInTextarea()
    if (!r || !draftBody.trim()) return
    const next: MarkdownAnchorComment = {
      id: newId(),
      start: r.start,
      end: r.end,
      quote: r.quote,
      body: draftBody.trim(),
      createdAt: Date.now(),
    }
    setComments((c) => [...c, next])
    setDraftBody('')
  }

  const addCommentFromPreviewSelection = () => {
    const sel = window.getSelection()
    if (!sel || sel.isCollapsed) return
    const text = sel.toString()
    if (!text.trim() || !draftBody.trim()) return

    let start = markdown.indexOf(text)
    if (start < 0) start = markdown.indexOf(text.trim())
    if (start < 0) {
      window.alert(
        'Could not map selection to the source text. Switch to Annotate and select in the raw markdown.'
      )
      return
    }
    const end = start + text.length
    const next: MarkdownAnchorComment = {
      id: newId(),
      start,
      end,
      quote: markdown.slice(start, end),
      body: draftBody.trim(),
      createdAt: Date.now(),
    }
    setComments((c) => [...c, next])
    setDraftBody('')
    sel.removeAllRanges()
  }

  const removeComment = (id: string) => {
    setComments((c) => c.filter((x) => x.id !== id))
  }

  const mdComponents = useMemo(
    () => ({
      h1: (p: { children?: ReactNode }) => (
        <h1 className="mb-3 mt-6 text-lg font-bold text-[var(--t1)] first:mt-0">
          {p.children}
        </h1>
      ),
      h2: (p: { children?: ReactNode }) => (
        <h2 className="mb-2 mt-5 text-base font-semibold text-[var(--t1)]">
          {p.children}
        </h2>
      ),
      h3: (p: { children?: ReactNode }) => (
        <h3 className="mb-2 mt-4 text-sm font-semibold text-[var(--t1)]">
          {p.children}
        </h3>
      ),
      p: (p: { children?: ReactNode }) => (
        <p className="mb-3 text-[13px] leading-relaxed text-[var(--t2)] last:mb-0">
          {p.children}
        </p>
      ),
      ul: (p: { children?: ReactNode }) => (
        <ul className="mb-3 list-disc space-y-1 pl-5 text-[13px] text-[var(--t2)]">
          {p.children}
        </ul>
      ),
      ol: (p: { children?: ReactNode }) => (
        <ol className="mb-3 list-decimal space-y-1 pl-5 text-[13px] text-[var(--t2)]">
          {p.children}
        </ol>
      ),
      li: (p: { children?: ReactNode }) => (
        <li className="leading-relaxed">{p.children}</li>
      ),
      blockquote: (p: { children?: ReactNode }) => (
        <blockquote className="mb-3 border-l-2 border-[var(--a5)]/50 pl-3 text-[var(--t3)] italic">
          {p.children}
        </blockquote>
      ),
      code: (p: { className?: string; children?: ReactNode }) => {
        const inline = !p.className
        if (inline) {
          return (
            <code className="rounded bg-black/35 px-1 py-0.5 font-mono text-[12px] text-amber-200/95">
              {p.children}
            </code>
          )
        }
        return (
          <pre className="mb-3 overflow-x-auto rounded border border-[var(--bd)] bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-[var(--t1)]">
            <code>{p.children}</code>
          </pre>
        )
      },
      pre: (p: { children?: ReactNode }) => <>{p.children}</>,
      a: (p: { href?: string; children?: ReactNode }) => (
        <a
          href={p.href}
          className="text-[var(--a5)] underline-offset-2 hover:underline"
          target="_blank"
          rel="noopener noreferrer"
        >
          {p.children}
        </a>
      ),
      table: (p: { children?: ReactNode }) => (
        <div className="mb-3 overflow-x-auto">
          <table className="min-w-full border-collapse text-left text-[12px] text-[var(--t2)]">
            {p.children}
          </table>
        </div>
      ),
      th: (p: { children?: ReactNode }) => (
        <th className="border border-[var(--bd)] bg-[var(--s2)] px-2 py-1 font-medium text-[var(--t1)]">
          {p.children}
        </th>
      ),
      td: (p: { children?: ReactNode }) => (
        <td className="border border-[var(--bd)] px-2 py-1">{p.children}</td>
      ),
      hr: () => <hr className="my-4 border-[var(--bd)]" />,
      strong: (p: { children?: ReactNode }) => (
        <strong className="font-semibold text-[var(--t1)]">{p.children}</strong>
      ),
    }),
    []
  )

  const previewSelectionText = () => {
    if (typeof window === 'undefined') return ''
    return window.getSelection()?.toString() ?? ''
  }

  void selVersion
  const canAddAnnotate =
    !!draftBody.trim() && selectionRangeInTextarea() !== null
  const canAddPreview =
    !!draftBody.trim() && previewSelectionText().trim().length > 0

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.06] pb-2">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--t4)]">
          Report
        </span>
        <div className="flex rounded border border-[var(--bd)] p-0.5">
          <button
            type="button"
            onClick={() => setTab('preview')}
            className={`rounded px-2 py-1 text-[11px] font-medium ${
              tab === 'preview'
                ? 'bg-[var(--a5)]/25 text-[var(--t1)]'
                : 'text-[var(--t3)] hover:text-[var(--t1)]'
            }`}
          >
            Preview
          </button>
          <button
            type="button"
            onClick={() => setTab('annotate')}
            className={`rounded px-2 py-1 text-[11px] font-medium ${
              tab === 'annotate'
                ? 'bg-[var(--a5)]/25 text-[var(--t1)]'
                : 'text-[var(--t3)] hover:text-[var(--t1)]'
            }`}
          >
            Annotate
          </button>
        </div>
        <span className="text-[10px] text-[var(--t4)]">
          {lineCount} lines · {comments.length} comment
          {comments.length === 1 ? '' : 's'}
        </span>
      </div>

      {tab === 'preview' ? (
        <div
          ref={previewRef}
          onMouseUp={() => setSelVersion((v) => v + 1)}
          className="min-h-[12rem] flex-1 overflow-y-auto rounded border border-[var(--bd)]/80 bg-[var(--bg)]/50 p-3"
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {markdown}
          </ReactMarkdown>
        </div>
      ) : (
        <div className="grid min-h-[12rem] flex-1 grid-cols-[2.5rem_1fr] gap-0 overflow-hidden rounded border border-[var(--bd)]/80 bg-[var(--bg)]/30 font-mono text-[11px] leading-5">
          <div
            ref={gutterRef}
            className="select-none overflow-hidden border-r border-[var(--bd)] bg-black/25 py-2 pr-1 text-right text-[var(--t4)]"
            aria-hidden
          >
            {lines.map((_, i) => (
              <div key={i} className="px-1">
                {i + 1}
              </div>
            ))}
          </div>
          <textarea
            ref={taRef}
            readOnly
            value={markdown}
            onScroll={syncScroll}
            onSelect={() => {
              syncScroll()
              setSelVersion((v) => v + 1)
            }}
            onMouseUp={() => setSelVersion((v) => v + 1)}
            className="min-h-[12rem] resize-none overflow-x-auto overflow-y-auto whitespace-pre bg-transparent py-2 pl-2 pr-2 text-[var(--t1)] outline-none"
            spellCheck={false}
          />
        </div>
      )}

      <div className="rounded border border-[var(--bd)]/60 bg-[var(--s1)]/80 p-2">
        <label className="block text-[10px] font-medium uppercase tracking-wide text-[var(--t4)]">
          Comment on selection
        </label>
        <p className="mt-0.5 text-[10px] text-[var(--t3)]">
          {tab === 'annotate'
            ? 'Select text in the source above, then write your note and click Add.'
            : 'Select text in the preview, then add your note (best match in source). For exact anchors, use Annotate.'}
        </p>
        <textarea
          value={draftBody}
          onChange={(e) => setDraftBody(e.target.value)}
          rows={2}
          placeholder="Your comment…"
          className="mt-2 w-full resize-y rounded border border-[var(--bd)] bg-[var(--bg)] px-2 py-1.5 text-[12px] text-[var(--t1)] placeholder:text-[var(--t4)] focus:outline-none focus:ring-1 focus:ring-[var(--a5)]"
        />
        <div className="mt-2 flex flex-wrap gap-2">
          {tab === 'annotate' ? (
            <button
              type="button"
              onClick={addCommentFromTextarea}
              disabled={!canAddAnnotate}
              className="rounded bg-[var(--a5)] px-3 py-1.5 text-[11px] font-medium text-slate-900 hover:bg-[var(--a4)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              Add comment on selection
            </button>
          ) : (
            <button
              type="button"
              onClick={addCommentFromPreviewSelection}
              disabled={!canAddPreview}
              className="rounded bg-[var(--a5)] px-3 py-1.5 text-[11px] font-medium text-slate-900 hover:bg-[var(--a4)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              Add comment on selection
            </button>
          )}
        </div>
      </div>

      {comments.length > 0 && (
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
          <p className="text-[10px] font-medium uppercase tracking-wide text-[var(--t4)]">
            Comments ({comments.length})
          </p>
          <ul className="space-y-2">
            {comments.map((c) => (
              <li
                key={c.id}
                className="rounded border border-[var(--bd)] bg-black/20 p-2 text-[11px]"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-[9px] text-[var(--t4)]">
                      chars {c.start}–{c.end} ·{' '}
                      {new Date(c.createdAt).toLocaleString()}
                    </p>
                    <blockquote className="mt-1 border-l-2 border-amber-500/40 pl-2 text-[var(--t3)]">
                      {c.quote.length > 280
                        ? `${c.quote.slice(0, 280)}…`
                        : c.quote}
                    </blockquote>
                    <p className="mt-2 whitespace-pre-wrap text-[var(--t1)]">
                      {c.body}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeComment(c.id)}
                    className="shrink-0 text-[10px] text-red-400/90 hover:underline"
                  >
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
