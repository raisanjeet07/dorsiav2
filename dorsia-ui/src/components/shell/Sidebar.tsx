'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const sections = [
  {
    title: 'Platform',
    items: [
      { label: 'Overview', href: '/' },
    ],
  },
  {
    title: 'Research',
    items: [
      { label: 'Research List', href: '/research' },
      { label: '+ New Research', href: '/research/new', accent: true },
    ],
  },
  {
    title: 'Organization',
    items: [
      { label: 'Settings', href: '/settings' },
    ],
  },
]

export function Sidebar() {
  const pathname = usePathname()

  const isActive = (href: string) => {
    if (href === '/' && pathname === '/') return true
    if (href !== '/' && pathname.startsWith(href)) return true
    return false
  }

  return (
    <aside className="hidden w-[224px] shrink-0 border-r border-[var(--bd)] bg-[var(--s1)] md:flex md:flex-col md:overflow-y-auto">
      <nav className="flex-1 px-3 py-6 space-y-8">
        {sections.map((section) => (
          <div key={section.title}>
            <h3 className="mb-3 px-3 text-xs font-semibold uppercase tracking-wide text-[var(--t3)]">
              {section.title}
            </h3>
            <ul className="space-y-2">
              {section.items.map((item) => {
                const active = isActive(item.href)
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={`
                        block px-3 py-2 rounded-lg transition-colors text-sm font-medium
                        ${
                          active
                            ? 'bg-amber-500/20 text-amber-500 border border-amber-500/30'
                            : item.accent
                              ? 'text-amber-400 hover:bg-[var(--s2)]'
                              : 'text-[var(--t2)] hover:bg-[var(--s2)]'
                        }
                      `}
                    >
                      {item.label}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  )
}
