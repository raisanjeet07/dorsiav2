'use client'

import { useEffect } from 'react'
import Link from 'next/link'

export default function ResearchWorkflowError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('research workflow page error', error)
  }, [error])

  return (
    <div className="min-h-[40vh] flex flex-col items-center justify-center px-4 text-center text-[var(--t1)]">
      <h1 className="text-xl font-semibold mb-2">Something went wrong</h1>
      <p className="text-[var(--t2)] text-sm mb-6 max-w-md break-words">
        {error.message || 'Failed to load this workflow.'}
      </p>
      {error.stack && process.env.NODE_ENV === 'development' && (
        <pre className="mb-6 max-h-40 max-w-2xl overflow-auto rounded border border-[var(--bd)] bg-black/40 p-3 text-left text-[10px] text-[var(--t3)]">
          {error.stack}
        </pre>
      )}
      <div className="flex gap-3">
        <button
          type="button"
          onClick={reset}
          className="px-4 py-2 bg-[var(--a5)] text-white rounded font-medium"
        >
          Try again
        </button>
        <Link
          href="/research"
          className="px-4 py-2 border border-[var(--bd)] rounded font-medium text-[var(--t1)]"
        >
          Back to list
        </Link>
      </div>
    </div>
  )
}
