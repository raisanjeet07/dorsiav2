'use client'
import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { ReviewComment } from '@/lib/types'

/** Avoid React "Objects are not valid as a React child" if API returns nested values. */
function safeText(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
    return String(v)
  }
  try {
    return JSON.stringify(v)
  } catch {
    return ''
  }
}

interface ReviewPanelProps {
  workflowId: string
  onSendMessage: (message: string) => void
  /** Live assistant reply text (streaming, USER_REVIEW chat only). */
  streamingReply: string
}

export function ReviewPanel({
  workflowId,
  onSendMessage,
  streamingReply,
}: ReviewPanelProps) {
  const [activeTab, setActiveTab] = useState<'comments' | 'chat'>('comments')
  const [reviews, setReviews] = useState<ReviewComment[]>([])
  const [loading, setLoading] = useState(true)
  const [messageInput, setMessageInput] = useState('')
  const [messages, setMessages] = useState<
    Array<{ role: 'user' | 'agent'; content: string }>
  >([])
  const chatEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const reviewData = await api.getReviews(workflowId)
        const rounds = Array.isArray(reviewData.reviews) ? reviewData.reviews : []
        const allComments = rounds
          .flatMap((r) => (Array.isArray(r.comments) ? r.comments : []))
          .slice(0, 20)
        setReviews(allComments)

        const convData = await api.getConversations(workflowId)
        const turns = Array.isArray(convData.conversations)
          ? convData.conversations
          : []

        const chatMessages = turns.map((c) => ({
          role: (c.role === 'user' ? 'user' : 'agent') as 'user' | 'agent',
          content:
            typeof c.content === 'string' ? c.content : safeText(c.content),
        }))
        setMessages(chatMessages)
      } catch (error) {
        console.error('Failed to load review data:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [workflowId])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingReply])

  const handleSendMessage = () => {
    if (!messageInput.trim()) return

    const userMessage = messageInput
    setMessageInput('')
    setMessages((prev) => {
      let next = [...prev]
      if (streamingReply.trim()) {
        next = [...next, { role: 'agent', content: streamingReply }]
      }
      next = [...next, { role: 'user', content: userMessage }]
      return next
    })
    onSendMessage(userMessage)
  }

  const severityColor: Record<string, string> = {
    critical: 'bg-red-500/20 text-red-400',
    high: 'bg-orange-500/20 text-orange-400',
    medium: 'bg-yellow-500/20 text-yellow-400',
    low: 'bg-blue-500/20 text-blue-400',
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-transparent">
      <div className="flex border-b border-[var(--bd)]">
        <button
          onClick={() => setActiveTab('comments')}
          className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
            activeTab === 'comments'
              ? 'text-[var(--a5)] border-b-2 border-[var(--a5)]'
              : 'text-[var(--t2)] hover:text-[var(--t1)]'
          }`}
        >
          Comments
        </button>
        <button
          onClick={() => setActiveTab('chat')}
          className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
            activeTab === 'chat'
              ? 'text-[var(--a5)] border-b-2 border-[var(--a5)]'
              : 'text-[var(--t2)] hover:text-[var(--t1)]'
          }`}
        >
          Chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {activeTab === 'comments' && (
          <div className="p-4 space-y-3">
            {loading ? (
              <div className="text-center py-8 text-[var(--t3)]">
                Loading comments...
              </div>
            ) : reviews.length === 0 ? (
              <div className="text-center py-8 text-[var(--t3)]">
                No review comments yet
              </div>
            ) : (
              reviews.map((comment, idx) => (
                <div
                  key={`${idx}-${safeText(comment.id)}`}
                  className="p-3 bg-[var(--bg-2)] rounded border border-[var(--bd)]"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${
                        severityColor[String(comment.severity)] ||
                        'bg-gray-100 text-gray-700'
                      }`}
                    >
                      {safeText(comment.severity)}
                    </span>
                    <span className="text-xs text-[var(--t3)]">
                      {safeText(comment.section)}
                    </span>
                  </div>
                  <p className="text-sm text-[var(--t1)] mb-2">
                    {safeText(comment.comment)}
                  </p>
                  {comment.recommendation && (
                    <p className="text-xs text-[var(--t2)] italic">
                      Recommendation: {safeText(comment.recommendation)}
                    </p>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'chat' && (
          <div className="flex flex-col h-full">
            <p className="px-4 pt-3 pb-1 text-xs text-[var(--t3)] leading-relaxed border-b border-[var(--bd)]">
              Chat is scoped to the <strong className="text-[var(--t2)]">draft report</strong> only. Ask
              questions, request additions, or outline edits for the final version. Use{' '}
              <strong className="text-[var(--t2)]">Request changes</strong> in the actions above to send
              structured feedback back to the agents.
            </p>
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {messages.length === 0 && !streamingReply ? (
                <div className="text-center py-8 text-[var(--t3)]">
                  No messages yet — ask something about the report.
                </div>
              ) : (
                <>
                  {messages.map((msg, idx) => (
                    <div
                      key={idx}
                      className={`flex ${
                        msg.role === 'user' ? 'justify-end' : 'justify-start'
                      }`}
                    >
                      <div
                        className={`max-w-[85%] px-3 py-2 rounded-lg text-sm whitespace-pre-wrap break-words ${
                          msg.role === 'user'
                            ? 'bg-[var(--a5)] text-white'
                            : 'bg-[var(--bg-2)] text-[var(--t1)] border border-[var(--bd)]'
                        }`}
                      >
                        {safeText(msg.content)}
                      </div>
                    </div>
                  ))}
                  {streamingReply ? (
                    <div className="flex justify-start">
                      <div className="max-w-[85%] px-3 py-2 rounded-lg text-sm bg-[var(--bg-2)] text-[var(--t1)] border border-[var(--bd)] whitespace-pre-wrap break-words">
                        {streamingReply}
                      </div>
                    </div>
                  ) : null}
                </>
              )}
              <div ref={chatEndRef} />
            </div>

            <div className="border-t border-[var(--bd)] p-3">
              <div className="flex gap-2 items-end">
                <textarea
                  value={messageInput}
                  onChange={(e) => setMessageInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      handleSendMessage()
                    }
                  }}
                  rows={3}
                  placeholder="Ask about the report or suggest edits for the final version…"
                  className="flex-1 min-h-[3rem] max-h-40 px-3 py-2 text-sm bg-[var(--bg-2)] text-[var(--t1)] border border-[var(--bd)] rounded focus:outline-none focus:ring-2 focus:ring-[var(--a5)] resize-y"
                />
                <button
                  onClick={handleSendMessage}
                  disabled={!messageInput.trim()}
                  className="px-3 py-2 bg-[var(--a5)] text-white rounded text-sm font-medium hover:bg-[var(--a4)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  Send
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
