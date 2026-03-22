import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { Shell } from '@/components/shell/Shell'

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' })

export const metadata: Metadata = {
  title: 'Dorsia · Platform',
  description: 'Multi-agent AI workflow platform',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${inter.variable} font-sans antialiased bg-[var(--bg)] min-h-screen text-[var(--t2)]`}
      >
        <Shell>{children}</Shell>
      </body>
    </html>
  )
}
