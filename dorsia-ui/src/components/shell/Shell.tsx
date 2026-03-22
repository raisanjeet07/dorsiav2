'use client'

import { TopNav } from './TopNav'
import { Sidebar } from './Sidebar'

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-[var(--bg)]">
      <TopNav />

      {/* Below fixed nav: sidebar + scrollable main (natural page scroll, no “frozen” pane) */}
      <div className="flex flex-1 flex-col pt-[52px] md:flex-row">
        <Sidebar />

        <main className="ds-page min-h-0 w-full min-w-0 flex-1 overflow-x-hidden overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  )
}
