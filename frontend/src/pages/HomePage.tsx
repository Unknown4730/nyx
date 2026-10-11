import { Link } from 'react-router-dom'

import { Chip, Panel, SectionHeading, ToneChip } from '@/components/ui'
import { humanise, num, relativeTime } from '@/lib/format'
import { outcomeTone } from '@/lib/tone'
import { useNyx } from '@/state/NyxProvider'
import type { SuitabilityOutcome } from '@/types/analysis'

const STEPS = [
  {
    title: 'Describe',
    body: 'Write the application in plain language, or start from a sample. Say what you know; leave the rest as “not stated”.',
  },
  {
    title: 'Analyse',
    body: 'Deterministic rules extract the signals, score serverless suitability with visible weights, and map each component to AWS, Google Cloud and Azure.',
  },
  {
    title: 'Decide',
    body: 'Read the verdict with its evidence, compare the current and proposed blueprints, then save, export or open the migration plan.',
  },
]

export function HomePage() {
  const { meta, backendOnline, aiStatus, stats, projects } = useNyx()
  const recent = (stats?.recent?.length ? stats.recent : projects).slice(0, 4)
  const online = backendOnline === true

  return (
    <div className="grid gap-10">
      <section className="grid gap-6 pt-6 md:pt-12">
        <p className="nyx-eyebrow">AI-assisted serverless migration · cloud architecture advisor</p>
        <h1 className="text-4xl font-semibold tracking-tight text-chalk sm:text-5xl lg:text-6xl">
          Rethink your <span className="text-acid">architecture.</span>
        </h1>
        <p className="max-w-2xl text-base leading-relaxed text-silver sm:text-lg">
          NYX tests whether a system should move to serverless, shows what it would look like on AWS, Google Cloud or Azure, and
          lists exactly what is still unknown. Every verdict is traceable to the rules and inputs behind it.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link to="/analyze" className="nyx-btn-primary">
            Start an analysis
          </Link>
          <Link to="/analyze#samples-heading" className="nyx-btn-secondary">
            Browse sample applications
          </Link>
          <Link to="/method" className="nyx-btn-ghost">
            How the scoring works
          </Link>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <Panel labelledBy="status-heading">
          <SectionHeading id="status-heading" eyebrow="System" title="Backend and engine" />
          <dl className="mt-5 grid grid-cols-2 gap-5">
            <div>
              <dt className="nyx-eyebrow">API</dt>
              <dd className="mt-2">
                <span
                  className={`nyx-chip ${online ? 'border-acid/35 bg-acid/10 text-acid' : backendOnline === false ? 'border-signal/40 bg-signal/10 text-signal' : 'border-chalk/[0.12] bg-chalk/[0.04] text-silver'}`}
                >
                  {online ? 'Online' : backendOnline === false ? 'Offline' : 'Checking'}
                </span>
              </dd>
            </div>
            <div>
              <dt className="nyx-eyebrow">Engine</dt>
              <dd className="nyx-metric mt-2 text-sm">{meta?.product.rule_pack_version ?? 'not stated'}</dd>
            </div>
            <div className="col-span-2">
              <dt className="nyx-eyebrow">AI assist</dt>
              <dd className="mt-2 text-sm text-chalk/90">
                {aiStatus ? `${humanise(aiStatus.status)} — ${aiStatus.message}` : 'Unknown until the API answers. The rules engine works without it.'}
              </dd>
            </div>
          </dl>
          {backendOnline === false ? (
            <p className="mt-5 rounded-xl border border-signal/30 bg-signal/[0.06] p-3 text-sm text-chalk/90">
              NYX cannot reach its API. Start the backend as described in the README, then reload this page.
            </p>
          ) : null}
        </Panel>

        <Panel labelledBy="recent-heading">
          <SectionHeading id="recent-heading" eyebrow="Library" title="Recent projects" />
          {recent.length === 0 ? (
            <p className="mt-4 text-sm text-silver">
              Nothing saved yet. Run an analysis and save it to see it here.
            </p>
          ) : (
            <ul className="mt-4 divide-y divide-chalk/[0.06]">
              {recent.map((project) => (
                <li key={project.id}>
                  <Link to={`/projects/${encodeURIComponent(project.id)}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-3 hover:text-acid">
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-chalk">{project.name}</span>
                    <ToneChip tone={outcomeTone(project.suitability_outcome as SuitabilityOutcome)}>{humanise(project.suitability_outcome)}</ToneChip>
                    <span className="text-2xs text-silver">{relativeTime(project.updated_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {stats ? (
            <div className="mt-5 flex flex-wrap gap-2">
              <Chip>{`${num(stats.total, '0')} stored`}</Chip>
              <Chip>{`${num(stats.user_projects, '0')} yours`}</Chip>
              <Chip>{`${num(stats.example_projects, '0')} samples`}</Chip>
            </div>
          ) : null}
        </Panel>
      </div>

      <section aria-labelledby="steps-heading" className="grid gap-4">
        <h2 id="steps-heading" className="nyx-eyebrow">
          How a result is produced
        </h2>
        <ol className="grid gap-4 md:grid-cols-3">
          {STEPS.map((step, index) => (
            <li key={step.title} className="nyx-glass-raised p-5">
              <span className="nyx-metric text-sm text-acid">0{index + 1}</span>
              <h3 className="mt-2 text-lg font-semibold text-chalk">{step.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-silver">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
