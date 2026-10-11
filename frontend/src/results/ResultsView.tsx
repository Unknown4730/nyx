import { useId, useRef, useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'

import { ErrorNotice, Chip } from '@/components/ui'
import { api, saveTextFile } from '@/lib/api'
import { humanise, relativeTime, slugify, timestamp } from '@/lib/format'
import { useNyx } from '@/state/NyxProvider'
import type { AnalysisResult } from '@/types/analysis'
import type { ExportFormat } from '@/types/nyx'

import { ArchitecturePanel } from './ArchitecturePanel'
import { CostPanel } from './CostPanel'
import { MigrationPanel } from './MigrationPanel'
import { OverviewPanel } from './OverviewPanel'
import { SecurityPanel } from './SecurityPanel'
import { ServicesPanel } from './ServicesPanel'

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'architecture', label: 'Architecture' },
  { id: 'services', label: 'Cloud services' },
  { id: 'cost', label: 'Cost model' },
  { id: 'security', label: 'Security' },
  { id: 'migration', label: 'Migration' },
] as const

type TabId = (typeof TABS)[number]['id']

function errorText(cause: unknown): string {
  return cause instanceof Error && cause.message ? cause.message : 'The export could not be completed.'
}

export function ResultsView({ result }: { result: AnalysisResult }) {
  const { projectId, saveProject, savedFlash, options } = useNyx()
  const [tab, setTab] = useState<TabId>('overview')
  const [busy, setBusy] = useState<ExportFormat | 'save' | null>(null)
  const [notice, setNotice] = useState<{ tone: 'error' | 'ok'; text: string } | null>(null)
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  const idBase = useId()

  const saved = Boolean(projectId)
  const aiAssisted = result.engine_mode === 'ai_assisted'
  const exportBlocked = !saved && aiAssisted

  function focusTab(index: number) {
    const next = TABS[(index + TABS.length) % TABS.length]
    setTab(next.id)
    tabRefs.current[next.id]?.focus()
  }

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      focusTab(index + 1)
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault()
      focusTab(index - 1)
    } else if (event.key === 'Home') {
      event.preventDefault()
      focusTab(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      focusTab(TABS.length - 1)
    }
  }

  async function handleSave() {
    setBusy('save')
    setNotice(null)
    const detail = await saveProject()
    setBusy(null)
    if (detail) {
      setNotice({ tone: 'ok', text: `Saved as “${detail.name}”.` })
    } else {
      setNotice({ tone: 'error', text: 'The analysis could not be saved. Check that the API is running and try again.' })
    }
  }

  async function handleExport(format: ExportFormat) {
    setBusy(format)
    setNotice(null)
    try {
      if (saved && projectId) {
        if (format === 'json') {
          const envelope = await api.exportProjectJson(projectId)
          saveTextFile(envelope.filename, envelope.content, 'application/json')
        } else {
          const text = await api.exportProjectMarkdown(projectId)
          saveTextFile(`nyx-report-${slugify(result.title)}.md`, text, 'text/markdown')
        }
      } else {
        // Not saved: re-run the deterministic rules on the same requirements.  The
        // AI layer is switched off so the re-run cannot differ from what is shown.
        const envelope = await api.exportAnalysis({
          requirements: result.application,
          options: {
            ...options,
            use_ai: false,
            providers: result.providers?.length ? result.providers : options.providers,
            default_provider: result.default_provider,
          },
          format,
        })
        saveTextFile(envelope.filename, envelope.content, format === 'json' ? 'application/json' : 'text/markdown')
      }
      setNotice({ tone: 'ok', text: `${format === 'json' ? 'JSON' : 'Markdown'} report downloaded.` })
    } catch (cause) {
      setNotice({ tone: 'error', text: errorText(cause) })
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="grid gap-6">
      <header className="nyx-glass p-5 sm:p-6">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className="nyx-eyebrow">Analysis result</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-chalk sm:text-3xl">{result.title}</h1>
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-silver">
              <span>{timestamp(result.created_at)}</span>
              <span aria-hidden="true">·</span>
              <span>{relativeTime(result.created_at)}</span>
              <span aria-hidden="true">·</span>
              <span className="font-mono">{result.analysis_id}</span>
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Chip>{aiAssisted ? 'AI-assisted inputs' : 'Deterministic rules engine'}</Chip>
              <Chip>{`Engine ${result.rule_pack_version}`}</Chip>
              {saved ? <Chip className="border-acid/35 text-acid">Saved to projects</Chip> : <Chip>Not saved yet</Chip>}
            </div>
          </div>
          <div className="flex flex-wrap gap-2 lg:justify-end">
            {!saved ? (
              <button type="button" className="nyx-btn-primary" onClick={handleSave} disabled={busy !== null}>
                {busy === 'save' ? 'Saving…' : 'Save project'}
              </button>
            ) : (
              <Link to="/projects" className="nyx-btn-secondary">
                View projects
              </Link>
            )}
            <button
              type="button"
              className="nyx-btn-secondary"
              onClick={() => handleExport('markdown')}
              disabled={busy !== null || exportBlocked}
              title={exportBlocked ? 'Save this AI-assisted analysis first so the exported report matches it exactly.' : undefined}
            >
              {busy === 'markdown' ? 'Preparing…' : 'Export Markdown'}
            </button>
            <button
              type="button"
              className="nyx-btn-secondary"
              onClick={() => handleExport('json')}
              disabled={busy !== null || exportBlocked}
              title={exportBlocked ? 'Save this AI-assisted analysis first so the exported report matches it exactly.' : undefined}
            >
              {busy === 'json' ? 'Preparing…' : 'Export JSON'}
            </button>
          </div>
        </div>
        {exportBlocked ? (
          <p className="mt-4 text-xs text-silver">
            This result used AI-assisted inputs, which cannot be reproduced exactly. Save it to export the stored copy.
          </p>
        ) : null}
        {savedFlash ? (
          <p role="status" className="mt-4 text-sm text-acid">
            Saved. It now appears under Projects.
          </p>
        ) : null}
        {notice ? (
          notice.tone === 'error' ? (
            <div className="mt-4">
              <ErrorNotice title="Something went wrong" message={notice.text} />
            </div>
          ) : (
            <p role="status" className="mt-4 text-sm text-acid">
              {notice.text}
            </p>
          )
        ) : null}
        <p className="mt-4 text-xs text-silver">
          Verdict: <span className="text-chalk">{humanise(result.suitability.outcome)}</span> · Complexity:{' '}
          <span className="text-chalk">{humanise(result.migration.overall_complexity)}</span>
        </p>
      </header>

      <nav aria-label="Result sections" className="nyx-scroll-x">
        <div role="tablist" aria-label="Result sections" className="flex min-w-max gap-1 rounded-2xl border border-chalk/[0.07] bg-carbon/70 p-1.5">
          {TABS.map((item, index) => (
            <button
              key={item.id}
              ref={(element) => {
                tabRefs.current[item.id] = element
              }}
              id={`${idBase}-tab-${item.id}`}
              role="tab"
              type="button"
              aria-selected={tab === item.id}
              aria-controls={`${idBase}-panel-${item.id}`}
              tabIndex={tab === item.id ? 0 : -1}
              className="nyx-tab"
              onClick={() => setTab(item.id)}
              onKeyDown={(event) => onTabKey(event, index)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </nav>

      {TABS.map((item) =>
        tab === item.id ? (
          <div
            key={item.id}
            id={`${idBase}-panel-${item.id}`}
            role="tabpanel"
            aria-labelledby={`${idBase}-tab-${item.id}`}
            tabIndex={0}
          >
            {item.id === 'overview' ? <OverviewPanel result={result} /> : null}
            {item.id === 'architecture' ? <ArchitecturePanel result={result} /> : null}
            {item.id === 'services' ? <ServicesPanel result={result} /> : null}
            {item.id === 'cost' ? <CostPanel result={result} /> : null}
            {item.id === 'security' ? <SecurityPanel result={result} /> : null}
            {item.id === 'migration' ? <MigrationPanel result={result} /> : null}
          </div>
        ) : null,
      )}
    </div>
  )
}
