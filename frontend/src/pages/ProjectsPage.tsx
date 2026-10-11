import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { EmptyState, ErrorNotice, Panel, SectionHeading, Stat, TD, TH, Table, ToneChip, Chip } from '@/components/ui'
import { decimal, humanise, num, relativeTime, timestamp } from '@/lib/format'
import { outcomeTone } from '@/lib/tone'
import { useNyx } from '@/state/NyxProvider'
import type { SuitabilityOutcome } from '@/types/analysis'

type Filter = 'all' | 'user' | 'example'

export function ProjectsPage() {
  const navigate = useNavigate()
  const { projects, stats, projectsError, refreshProjects, openProject, deleteProject } = useNyx()
  const [filter, setFilter] = useState<Filter>('all')
  const [confirming, setConfirming] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const visible = useMemo(() => projects.filter((item) => (filter === 'all' ? true : filter === 'user' ? item.kind === 'user_project' : item.kind === 'example_project')), [projects, filter])

  async function handleOpen(id: string) {
    const detail = await openProject(id)
    if (detail) navigate(`/projects/${encodeURIComponent(id)}`)
  }

  async function handleDelete(id: string) {
    setBusy(id)
    await deleteProject(id)
    setBusy(null)
    setConfirming(null)
  }

  return (
    <div className="grid gap-8">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="nyx-eyebrow">Projects</p>
          <h1 className="nyx-title mt-1">Saved analyses</h1>
          <p className="nyx-subtitle mt-2 max-w-2xl">Each project keeps the full result, so reopening it shows exactly what you saw, including after a restart.</p>
        </div>
        <Link to="/analyze" className="nyx-btn-primary">
          New analysis
        </Link>
      </header>

      {stats ? (
        <Panel>
          <dl className="grid grid-cols-2 gap-6 md:grid-cols-4">
            <Stat label="Stored" value={num(stats.total, '0')} />
            <Stat label="Your projects" value={num(stats.user_projects, '0')} />
            <Stat label="Samples" value={num(stats.example_projects, '0')} hint="Built-in examples" />
            <Stat label="Average score" value={decimal(stats.average_user_score, 1, '—')} hint="Your projects only" />
          </dl>
        </Panel>
      ) : null}

      <Panel labelledBy="list-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SectionHeading id="list-heading" eyebrow="Library" title="Projects" />
          <div className="flex rounded-xl border border-chalk/10 bg-obsidian/60 p-1" role="group" aria-label="Filter projects">
            {(
              [
                ['all', 'All'],
                ['user', 'Mine'],
                ['example', 'Samples'],
              ] as const
            ).map(([value, label]) => (
              <button key={value} type="button" className="nyx-tab" aria-pressed={filter === value} onClick={() => setFilter(value)}>
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-5">
          {projectsError ? (
            <ErrorNotice title="Saved projects could not be loaded" message={projectsError} onRetry={() => void refreshProjects()} />
          ) : projects.length === 0 ? (
            <EmptyState
              title="No saved projects yet"
              action={
                <Link to="/analyze" className="nyx-btn-primary">
                  Run your first analysis
                </Link>
              }
            >
              Run an analysis and choose “Save project” to keep it here.
            </EmptyState>
          ) : visible.length === 0 ? (
            <p className="text-sm text-silver">No projects match this filter.</p>
          ) : (
            <Table caption="Saved projects">
              <thead>
                <tr>
                  <th className={TH}>Project</th>
                  <th className={TH}>Verdict</th>
                  <th className={TH}>Score</th>
                  <th className={TH}>Components</th>
                  <th className={TH}>Updated</th>
                  <th className={TH}>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((project) => (
                  <tr key={project.id} className="align-top">
                    <td className={TD}>
                      <p className="font-medium text-chalk">{project.name}</p>
                      <p className="mt-0.5 flex flex-wrap items-center gap-2 text-2xs text-silver">
                        <Chip>{project.kind === 'example_project' ? 'Sample' : 'Saved'}</Chip>
                        <span>{humanise(project.application_type, 'Type not stated')}</span>
                      </p>
                      {project.excerpt ? <p className="mt-1 line-clamp-2 max-w-md text-xs text-silver">{project.excerpt}</p> : null}
                    </td>
                    <td className={TD}>
                      <ToneChip tone={outcomeTone(project.suitability_outcome as SuitabilityOutcome)}>
                        {humanise(project.suitability_outcome)}
                      </ToneChip>
                    </td>
                    <td className={`${TD} nyx-metric`}>{decimal(project.suitability_score, 1)}</td>
                    <td className={`${TD} nyx-metric`}>{num(project.component_count, '0')}</td>
                    <td className={`${TD} text-xs text-silver`} title={timestamp(project.updated_at)}>
                      {relativeTime(project.updated_at)}
                    </td>
                    <td className={`${TD} whitespace-nowrap`}>
                      <div className="flex justify-end gap-2">
                        <button type="button" className="nyx-btn-secondary px-3 py-1.5 text-xs" onClick={() => void handleOpen(project.id)}>
                          Open
                        </button>
                        {confirming === project.id ? (
                          <>
                            <button
                              type="button"
                              className="nyx-btn-danger px-3 py-1.5 text-xs"
                              onClick={() => void handleDelete(project.id)}
                              disabled={busy === project.id}
                            >
                              {busy === project.id ? 'Deleting…' : 'Confirm delete'}
                            </button>
                            <button type="button" className="nyx-btn-ghost px-2 py-1.5 text-xs" onClick={() => setConfirming(null)}>
                              Cancel
                            </button>
                          </>
                        ) : (
                          <button type="button" className="nyx-btn-ghost px-2 py-1.5 text-xs" onClick={() => setConfirming(project.id)}>
                            Delete
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </div>
      </Panel>
    </div>
  )
}
