/**
 * NYX application shell.
 *
 * Cycle 0a stops here on purpose: the entry point, the shared state provider and
 * the typed API client are wired and observable, while the requirements form, the
 * architecture workspace and the results pages arrive in later cycles.
 *
 * Everything named or counted on this page comes from the API (`/api/health`,
 * `/api/meta`, `/api/ai/status`, `/api/projects`, `/api/projects/stats`) or is
 * explicitly labelled as not built yet.  There are no placeholder metrics and no
 * simulated analysis results.
 */
import { useState } from 'react'

import { decimal, humanise, num, relativeTime } from '@/lib/format'
import { useNyx } from '@/state/NyxProvider'
import type { MetaPayload } from '@/types/nyx'

/** Work that does not exist yet, named so the shell is never mistaken for the app. */
const NOT_BUILT_YET: { title: string; cycle: string; detail: string }[] = [
  {
    title: 'New analysis',
    cycle: 'Cycle 2',
    detail: 'Requirements form driven by /api/meta, template cards and the analysis run itself.',
  },
  {
    title: 'Results',
    cycle: 'Cycle 3',
    detail: 'Suitability, security, cost and migration panels rendered from the analysis result.',
  },
  {
    title: 'Architecture workspace',
    cycle: 'Cycle 4',
    detail: 'Conventional and proposed blueprints on the canvas, plus the component inspector.',
  },
  {
    title: 'Saving and exports',
    cycle: 'Cycle 5',
    detail: 'Opening, deleting and exporting stored analyses as JSON or Markdown.',
  },
]

type ConnectionState = 'checking' | 'online' | 'offline'

/** The "N" mark, drawn solid from the current text colour (no gradients). */
function BrandMark() {
  return (
    <svg
      viewBox="0 0 64 64"
      className="h-10 w-10 shrink-0 rounded-[13px] bg-ink text-soft ring-1 ring-hairline"
      aria-hidden="true"
    >
      <path
        d="M18 46V18l28 28V18"
        fill="none"
        stroke="currentColor"
        strokeWidth={5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function ConnectionChip({ state }: { state: ConnectionState }) {
  const tone =
    state === 'online'
      ? 'border-signal-strong/30 bg-signal-strong/10 text-signal-strong'
      : state === 'offline'
        ? 'border-signal-partial/30 bg-signal-partial/10 text-signal-partial'
        : 'border-hairline bg-white/[0.04] text-muted'
  const label = state === 'online' ? 'Backend online' : state === 'offline' ? 'Backend unavailable' : 'Checking backend'
  return (
    <span className={`rounded-chip border px-3 py-1 text-2xs font-semibold uppercase tracking-[0.14em] ${tone}`}>
      {label}
    </span>
  )
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="nyx-eyebrow">{label}</dt>
      <dd className={`truncate text-sm text-soft ${mono ? 'font-mono' : ''}`} title={value}>
        {value}
      </dd>
    </div>
  )
}

function ProductFacts({ meta }: { meta: MetaPayload }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
      <Fact label="Product" value={meta.product.title} />
      <Fact label="Version" value={meta.product.version} />
      <Fact label="Contract schema" value={meta.product.schema_version} mono />
      <Fact label="Rule pack" value={meta.product.rule_pack_version} mono />
      <Fact label="Service catalogue" value={meta.product.catalog_version} mono />
      <Fact label="Cost model" value={meta.product.cost_model_version} mono />
    </dl>
  )
}

export function App() {
  const { meta, metaError, aiStatus, backendOnline, projects, stats, projectsError, refreshBackend } = useNyx()
  const [retrying, setRetrying] = useState(false)

  const connection: ConnectionState = backendOnline === null ? 'checking' : backendOnline ? 'online' : 'offline'

  async function handleRetry() {
    setRetrying(true)
    try {
      await refreshBackend()
    } finally {
      setRetrying(false)
    }
  }

  return (
    <div className="flex min-h-full flex-col bg-void">
      <header className="border-b border-hairline bg-ink/80">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-4 px-6 py-4">
          <BrandMark />
          <div className="min-w-0">
            <h1 className="font-mono text-lg font-semibold tracking-[0.24em] text-white">NYX</h1>
            <p className="truncate text-2xs text-muted">
              {meta?.product.tagline ?? 'AI-assisted serverless migration and cloud architecture advisor'}
            </p>
          </div>
          <span className="ml-auto">
            <ConnectionChip state={connection} />
          </span>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-8">
        <section aria-live="polite" className="nyx-panel nyx-hairline-top p-5">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-sm font-semibold text-white">Backend</h2>
            <ConnectionChip state={connection} />
            {connection === 'offline' ? (
              <button
                type="button"
                onClick={handleRetry}
                disabled={retrying}
                className="rounded-lg border border-hairline bg-raised px-3 py-1.5 text-sm text-soft transition-colors hover:bg-overlay disabled:opacity-60"
              >
                {retrying ? 'Retrying…' : 'Retry connection'}
              </button>
            ) : null}
          </div>

          {metaError ? <p className="mt-3 text-sm text-signal-partial">{metaError}</p> : null}

          <div className="mt-4">
            {meta ? (
              <ProductFacts meta={meta} />
            ) : (
              <p className="text-sm text-muted">
                {connection === 'checking'
                  ? 'Reading /api/meta for the product, schema and catalogue versions…'
                  : 'Product metadata is unavailable because /api/meta did not answer. Nothing is shown in its place.'}
              </p>
            )}
          </div>

          <div className="mt-5 border-t border-hairline pt-4">
            <h3 className="nyx-eyebrow">AI assist</h3>
            <p className="mt-1 text-sm text-soft">
              {aiStatus
                ? `${humanise(aiStatus.status)} — ${aiStatus.message}`
                : 'Unknown until /api/ai/status answers. The deterministic rules engine is unaffected.'}
            </p>
          </div>
        </section>

        <section className="nyx-panel p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="text-sm font-semibold text-white">Saved projects</h2>
            <span className="nyx-eyebrow">Read-only in this cycle</span>
          </div>

          {projectsError ? (
            <p className="mt-3 text-sm text-signal-partial">{projectsError}</p>
          ) : projects.length === 0 ? (
            <p className="mt-3 text-sm text-muted">
              {stats ? 'No saved projects yet.' : 'Loading saved projects…'} Running an analysis is part of Cycle 2.
            </p>
          ) : (
            <>
              {stats ? (
                <p className="mt-2 text-sm text-soft">
                  <span className="nyx-metric mr-2 text-base">{num(stats.total)}</span>
                  stored · {num(stats.user_projects)} user · {num(stats.example_projects)} example
                  {stats.newest ? ` · newest ${relativeTime(stats.newest)}` : ''}
                </p>
              ) : null}
              <ul className="mt-3 divide-y divide-hairline/70">
                {projects.slice(0, 5).map((project) => (
                  <li key={project.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
                    <span className="truncate text-sm text-soft">{project.name}</span>
                    <span className="nyx-eyebrow">{humanise(project.suitability_outcome)}</span>
                    <span className="font-mono text-2xs tabular-nums text-muted">
                      {decimal(project.suitability_score, 1)}
                    </span>
                    <span className="ml-auto text-2xs text-muted">{relativeTime(project.updated_at)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section>
          <h2 className="nyx-eyebrow">Not built yet</h2>
          <p className="mt-2 max-w-2xl text-sm text-muted">
            Cycle 0a repairs the foundation — entry point, state, API client and contract handling. These surfaces are
            listed so the shell is not mistaken for a working application.
          </p>
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {NOT_BUILT_YET.map((item) => (
              <li key={item.title} className="nyx-inset p-4">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-sm font-medium text-soft">{item.title}</p>
                  <span className="nyx-eyebrow">{item.cycle}</span>
                </div>
                <p className="mt-1 text-2xs text-muted">{item.detail}</p>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="border-t border-hairline px-6 py-4">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-muted">
          <span>NYX web client · Cycle 0a foundation</span>
          {meta ? <span className="font-mono">{meta.product.schema_version}</span> : null}
        </div>
      </footer>
    </div>
  )
}
