'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'

export default function NewResearchPage() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [form, setForm] = useState({
    topic: '',
    context: '',
    depth: 'standard' as 'shallow' | 'standard' | 'deep',
    max_review_cycles: 3,
  })

  const handleChange = (
    e: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>
  ) => {
    const { name, value } = e.target
    setForm((prev) => ({
      ...prev,
      [name]:
        name === 'max_review_cycles' ? parseInt(value, 10) || 3 : value,
    }))
  }

  const handleDepthChange = (depth: 'shallow' | 'standard' | 'deep') => {
    setForm((prev) => ({ ...prev, depth }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    if (!form.topic.trim()) {
      setError('Topic is required')
      setLoading(false)
      return
    }

    try {
      const response = await api.createWorkflow({
        topic: form.topic,
        context: form.context || undefined,
        depth: form.depth,
        max_review_cycles: form.max_review_cycles,
      })

      router.push(`/research/${response.workflow_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create workflow')
      setLoading(false)
    }
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-[var(--bg)] text-[var(--t1)]">
      <div className="max-w-2xl mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold mb-2">Start a New Research</h1>
          <p className="text-[var(--t2)]">
            Define your research topic and parameters
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {error && (
            <div className="p-4 bg-red-500/10 text-red-400 rounded border border-red-500/30">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium mb-2 text-[var(--t1)]">
              Research Topic*
            </label>
            <textarea
              name="topic"
              value={form.topic}
              onChange={handleChange}
              placeholder="Enter your research topic..."
              rows={4}
              className="w-full px-4 py-3 bg-[var(--bg-2)] text-[var(--t1)] border border-[var(--bd)] rounded focus:outline-none focus:ring-2 focus:ring-[var(--a5)] resize-none"
            />
            <p className="text-xs text-[var(--t3)] mt-1">
              Be specific and detailed for best results
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2 text-[var(--t1)]">
              Additional Context
            </label>
            <textarea
              name="context"
              value={form.context}
              onChange={handleChange}
              placeholder="Optional: Any background context, constraints, or specific requirements..."
              rows={3}
              className="w-full px-4 py-3 bg-[var(--bg-2)] text-[var(--t1)] border border-[var(--bd)] rounded focus:outline-none focus:ring-2 focus:ring-[var(--a5)] resize-none"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-3 text-[var(--t1)]">
              Research Depth
            </label>
            <div className="space-y-2">
              {(['shallow', 'standard', 'deep'] as const).map((depth) => (
                <label
                  key={depth}
                  className="flex items-center gap-3 p-3 border border-[var(--bd)] rounded cursor-pointer hover:bg-[var(--bg-2)] transition-colors"
                >
                  <input
                    type="radio"
                    name="depth"
                    value={depth}
                    checked={form.depth === depth}
                    onChange={() => handleDepthChange(depth)}
                    className="w-4 h-4 cursor-pointer"
                  />
                  <div>
                    <div className="font-medium capitalize">{depth}</div>
                    <div className="text-xs text-[var(--t3)]">
                      {depth === 'shallow'
                        ? 'Quick overview, 1-2 review cycles'
                        : depth === 'standard'
                          ? 'Balanced coverage, 3-4 review cycles'
                          : 'Comprehensive analysis, 5+ review cycles'}
                    </div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2 text-[var(--t1)]">
              Max Review Cycles
            </label>
            <input
              type="number"
              name="max_review_cycles"
              value={form.max_review_cycles}
              onChange={handleChange}
              min="1"
              max="10"
              className="w-full px-4 py-3 bg-[var(--bg-2)] text-[var(--t1)] border border-[var(--bd)] rounded focus:outline-none focus:ring-2 focus:ring-[var(--a5)]"
            />
            <p className="text-xs text-[var(--t3)] mt-1">
              Number of review iterations before final approval (1-10)
            </p>
          </div>

          <div className="flex gap-3 pt-4">
            <button
              type="submit"
              disabled={loading}
              className="px-6 py-3 bg-[var(--a5)] text-white rounded font-medium hover:bg-[var(--a4)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? 'Creating...' : 'Create Research'}
            </button>
            <button
              type="button"
              onClick={() => router.back()}
              className="px-6 py-3 border border-[var(--bd)] text-[var(--t1)] rounded font-medium hover:bg-[var(--bg-2)] transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
