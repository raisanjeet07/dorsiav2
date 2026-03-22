'use client'

export default function SettingsPage() {
  return (
    <div className="h-full min-h-0 overflow-y-auto max-w-2xl mx-auto px-4 py-10 text-[var(--t1)]">
      <h1 className="text-2xl font-bold mb-2">Settings</h1>
      <p className="text-[var(--t2)] text-sm mb-6">
        Organization and account settings will be configured here. For research
        workflows, connect the UI to the research API via{' '}
        <code className="text-[var(--a5)]">NEXT_PUBLIC_API_URL</code> and{' '}
        <code className="text-[var(--a5)]">NEXT_PUBLIC_WS_URL</code> in{' '}
        <code className="text-[var(--a5)]">.env.local</code>.
      </p>
    </div>
  )
}
