'use client'

import Link from 'next/link'

export function TopNav() {
  return (
    <nav className="fixed top-0 left-0 right-0 z-50 flex h-[52px] items-center justify-between border-b border-white/[0.06] bg-[var(--s1)]/90 backdrop-blur-md supports-[backdrop-filter]:bg-[var(--s1)]/75">
      {/* Left: Logo and Title */}
      <div className="flex min-w-0 flex-1 items-center gap-3 px-4 sm:px-6">
        <Link href="/" className="flex min-w-0 items-center gap-2 sm:gap-3">
          {/* Logo: Amber gradient square with "D" */}
          <div className="flex h-8 w-8 items-center justify-center rounded bg-gradient-to-br from-amber-400 to-amber-600">
            <span className="text-sm font-bold text-slate-900">D</span>
          </div>
          <span className="truncate text-base font-semibold text-[var(--t1)] sm:text-lg">
            Dorsia
          </span>
        </Link>

        {/* Mobile: primary nav (sidebar hidden) */}
        <nav className="ml-2 flex max-w-[55vw] items-center gap-1 overflow-x-auto md:hidden">
          <Link
            href="/research"
            className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-[var(--t2)] hover:bg-[var(--s2)]"
          >
            Research
          </Link>
          <Link
            href="/research/new"
            className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-amber-400/90 hover:bg-amber-500/10"
          >
            + New
          </Link>
          <Link
            href="/settings"
            className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-[var(--t3)] hover:bg-[var(--s2)]"
          >
            Settings
          </Link>
        </nav>
      </div>

      {/* Right: Actions */}
      <div className="flex shrink-0 items-center gap-2 px-4 sm:gap-4 sm:px-6">
        {/* Notification Bell */}
        <button className="p-2 rounded-lg hover:bg-[var(--s2)] transition-colors text-[var(--t2)]">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
          </svg>
        </button>

        {/* Command Palette Button */}
        <button className="px-3 py-1.5 rounded-lg bg-[var(--s2)] border border-[var(--bd)] text-[var(--t3)] text-sm hover:bg-[var(--s3)] transition-colors font-mono">
          ⌘K
        </button>

        {/* User Avatar */}
        <button className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-amber-400 to-amber-600 text-sm font-semibold text-slate-900 hover:opacity-90 transition-opacity">
          S
        </button>
      </div>
    </nav>
  )
}
