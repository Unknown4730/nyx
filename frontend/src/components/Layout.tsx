import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useEffect } from 'react'

import { useNyx } from '@/state/NyxProvider'

const NAV = [
  { to: '/', label: 'Home', end: true },
  { to: '/analyze', label: 'New analysis' },
  { to: '/results', label: 'Results' },
  { to: '/projects', label: 'Projects' },
  { to: '/method', label: 'Method' },
] as const

function Mark() {
  return (
    <svg viewBox="0 0 64 64" className="h-9 w-9 shrink-0 rounded-[11px] bg-elevated text-chalk ring-1 ring-chalk/10" aria-hidden="true">
      <path d="M19 45V19l26 26V19" fill="none" stroke="currentColor" strokeWidth={5} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="51" cy="13" r="3.5" fill="#D7FF3F" />
    </svg>
  )
}

export function Layout() {
  const { meta, backendOnline, refreshBackend } = useNyx()
  const location = useLocation()

  // Each page starts at the top; the router otherwise keeps the scroll position.
  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [location.pathname])

  const status =
    backendOnline === null ? { label: 'Checking API', tone: 'border-chalk/[0.12] text-silver' } : backendOnline ? { label: 'API online', tone: 'border-acid/35 text-acid' } : { label: 'API offline', tone: 'border-signal/40 text-signal' }

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-acid focus:px-3 focus:py-2 focus:text-obsidian">
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-chalk/[0.07] bg-obsidian/80 backdrop-blur-md">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-5 py-3.5 sm:px-8">
          <NavLink to="/" className="flex items-center gap-3" aria-label="NYX home">
            <Mark />
            <span className="min-w-0">
              <span className="block font-mono text-base font-semibold tracking-[0.28em] text-chalk">NYX</span>
              <span className="block truncate text-2xs text-silver">{meta?.product.tagline ?? 'Rethink your architecture.'}</span>
            </span>
          </NavLink>
          <nav aria-label="Primary" className="order-3 flex w-full items-center gap-1 overflow-x-auto sm:order-none sm:w-auto">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={'end' in item ? item.end : false}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${isActive ? 'bg-chalk/[0.09] text-chalk' : 'text-silver hover:text-chalk'}`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => void refreshBackend()}
              className={`nyx-chip bg-transparent transition-colors hover:bg-chalk/[0.05] ${status.tone}`}
              aria-label={`${status.label}. Check again`}
              title="Check the API again"
            >
              {status.label}
            </button>
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-5 py-8 sm:px-8 sm:py-10">
        <Outlet />
      </main>

      <footer className="border-t border-chalk/[0.07]">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-5 gap-y-2 px-5 py-6 text-2xs text-silver sm:px-8">
          <span className="font-mono tracking-[0.2em] text-chalk/80">NYX</span>
          <span>AI-assisted serverless migration and cloud architecture advisor</span>
          {meta ? (
            <span className="font-mono">
              engine {meta.product.rule_pack_version} · catalogue {meta.product.catalog_version} · schema {meta.product.schema_version}
            </span>
          ) : null}
          <span className="sm:ml-auto">Estimates are relative model units, not prices.</span>
        </div>
      </footer>
    </div>
  )
}
