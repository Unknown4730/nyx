/**
 * Application state for a NYX session.
 *
 * Kept deliberately small: metadata + AI status are fetched once, the current
 * analysis result lives here (mirrored into sessionStorage so a refresh does not
 * lose it), and the canvas view choices (provider, architecture, selection) are
 * shared between the canvas and the inspector without prop-drilling.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { api, NyxApiError } from '@/lib/api'
import type {
  AnalysisOptions,
  AnalysisResult,
  ArchitectureGraph,
  CloudProvider,
  Component,
  ProjectDetail,
  ProjectSummary,
} from '@/types/analysis'
import type { AiStatus, DraftEnvelope, MetaPayload, ProjectStats, RequirementDraft } from '@/types/nyx'
import { EMPTY_DRAFT, toRequest } from '@/types/nyx'

const DRAFT_KEY = 'nyx.draft.v1'

export const DEFAULT_OPTIONS: AnalysisOptions = {
  use_ai: true,
  providers: ['aws', 'gcp', 'azure'],
  default_provider: null,
  max_operations_per_view: 14,
  include_conventional_view: true,
  include_security_review: true,
  include_cost_estimate: true,
  include_migration_plan: true,
  locale: 'en',
  verbose: false,
}

type Status = 'idle' | 'running' | 'ready' | 'error'

interface NyxValue {
  meta: MetaPayload | null
  metaError: string | null
  aiStatus: AiStatus | null
  backendOnline: boolean | null

  draft: RequirementDraft
  patchDraft: (patch: Partial<RequirementDraft>) => void
  resetDraft: () => void
  applyTemplate: (id: string) => void

  options: AnalysisOptions
  patchOptions: (patch: Partial<AnalysisOptions>) => void

  status: Status
  error: string | null
  fieldErrors: Record<string, string>
  result: AnalysisResult | null
  run: () => Promise<AnalysisResult | null>
  openProject: (id: string) => Promise<ProjectDetail | null>
  clearResult: () => void

  projectId: string | null
  saveProject: (name?: string) => Promise<ProjectDetail | null>
  savedFlash: string | null
  projects: ProjectSummary[]
  stats: ProjectStats | null
  projectsError: string | null
  refreshProjects: () => Promise<void>
  deleteProject: (id: string) => Promise<void>

  provider: CloudProvider
  setProvider: (provider: CloudProvider) => void
  view: string
  setView: (view: string) => void
  graph: ArchitectureGraph | null
  selectedId: string | null
  select: (id: string | null) => void
  selectedComponent: Component | null
}

const NyxContext = createContext<NyxValue | null>(null)

function readStoredDraft(): DraftEnvelope | null {
  try {
    const raw = window.sessionStorage.getItem(DRAFT_KEY)
    return raw ? (JSON.parse(raw) as DraftEnvelope) : null
  } catch {
    return null
  }
}

function writeStoredDraft(envelope: DraftEnvelope) {
  try {
    window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify(envelope))
  } catch {
    /* A full or unavailable storage must never break the analysis. */
  }
}

export function clearStoredDraft() {
  try {
    window.sessionStorage.removeItem(DRAFT_KEY)
  } catch {
    /* ignore */
  }
}

export function NyxProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<MetaPayload | null>(null)
  const [metaError, setMetaError] = useState<string | null>(null)
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null)
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null)

  const stored = useRef<DraftEnvelope | null>(readStoredDraft())
  const [draft, setDraft] = useState<RequirementDraft>(stored.current?.draft ?? EMPTY_DRAFT)
  const [options, setOptions] = useState<AnalysisOptions>({ ...DEFAULT_OPTIONS, ...(stored.current?.options ?? {}) })
  const [result, setResult] = useState<AnalysisResult | null>(stored.current?.result ?? null)
  const [projectId, setProjectId] = useState<string | null>(null)

  const [status, setStatus] = useState<Status>(stored.current?.result ? 'ready' : 'idle')
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [stats, setStats] = useState<ProjectStats | null>(null)
  const [projectsError, setProjectsError] = useState<string | null>(null)
  const [savedFlash, setSavedFlash] = useState<string | null>(null)

  const [provider, setProvider] = useState<CloudProvider>(
    (stored.current?.result?.default_provider as CloudProvider) ?? 'aws',
  )
  const [view, setView] = useState<string>(stored.current?.result?.primary_view ?? 'proposed')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [payload, health, ai] = await Promise.all([api.meta(), api.health(), api.aiStatus()])
        if (cancelled) return
        setMeta(payload)
        setAiStatus(ai)
        setBackendOnline(health.status === 'ok' || health.status === 'degraded')
        setMetaError(null)
        if (!stored.current?.result) {
          setOptions((current) => ({
            ...current,
            max_operations_per_view: payload.limits.max_operations_per_view.default,
          }))
        }
      } catch (cause) {
        if (cancelled) return
        setBackendOnline(false)
        setMetaError(cause instanceof Error ? cause.message : 'The metadata endpoint is unavailable.')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const refreshProjects = useCallback(async () => {
    try {
      const [items, summary] = await Promise.all([api.listProjects(60), api.projectStats()])
      setProjects(items)
      setStats(summary)
      setProjectsError(null)
    } catch (cause) {
      setProjectsError(cause instanceof Error ? cause.message : 'Saved projects could not be loaded.')
    }
  }, [])

  useEffect(() => {
    void refreshProjects()
  }, [refreshProjects])

  const patchDraft = useCallback((patch: Partial<RequirementDraft>) => {
    setDraft((current) => ({ ...current, ...patch }))
    setFieldErrors({})
  }, [])

  const patchOptions = useCallback((patch: Partial<AnalysisOptions>) => {
    setOptions((current) => ({ ...current, ...patch }))
  }, [])

  const resetDraft = useCallback(() => {
    setDraft(EMPTY_DRAFT)
    setOptions(DEFAULT_OPTIONS)
    setResult(null)
    setProjectId(null)
    setStatus('idle')
    setError(null)
    setFieldErrors({})
    setSelectedId(null)
    clearStoredDraft()
  }, [])

  const applyTemplate = useCallback(
    (id: string) => {
      const template = meta?.templates.find((item) => item.id === id)
      if (!template) return
      const form = template.form
      setDraft({
        name: form.name ?? template.name,
        description: form.description ?? '',
        expected_users: form.expected_users != null ? String(form.expected_users) : '',
        traffic_pattern: form.traffic_pattern ?? 'unknown',
        application_type: form.application_type ?? 'unknown',
        availability: form.availability ?? 'unknown',
        budget: form.budget ?? 'balanced',
        preferred_provider: form.preferred_provider ?? 'none',
        data_storage: form.data_storage ?? [],
        additional_requirements: form.additional_requirements ?? '',
        template_id: template.id,
      })
      setResult(null)
      setStatus('idle')
      setError(null)
      setSelectedId(null)
    },
    [meta],
  )

  const persist = useCallback(
    (nextResult: AnalysisResult | null, nextDraft: RequirementDraft, nextOptions: AnalysisOptions) => {
      writeStoredDraft({ savedAt: new Date().toISOString(), draft: nextDraft, options: nextOptions, result: nextResult })
    },
    [],
  )

  const run = useCallback(async () => {
    setStatus('running')
    setError(null)
    setFieldErrors({})
    try {
      const payload = toRequest(draft, options)
      const next = await api.analyze(payload)
      setResult(next)
      setProvider(next.default_provider ?? 'aws')
      setView(next.primary_view ?? 'proposed')
      setSelectedId(null)
      setStatus('ready')
      persist(next, draft, options)
      return next
    } catch (cause) {
      const message = cause instanceof NyxApiError ? cause.message : 'The analysis could not be completed.'
      setError(message)
      setStatus('error')
      if (cause instanceof NyxApiError && cause.status === 422 && Array.isArray(cause.detail)) {
        const map: Record<string, string> = {}
        for (const item of cause.detail as { loc?: (string | number)[]; msg?: string }[]) {
          const field = (item.loc ?? []).filter((part) => part !== 'body').map(String).join('.')
          if (field) map[field] = item.msg ?? 'invalid value'
        }
        setFieldErrors(map)
      }
      return null
    }
  }, [draft, options, persist])

  const openProject = useCallback(
    async (id: string) => {
      setStatus('running')
      setError(null)
      try {
        const detail = await api.getProject(id)
        setResult(detail.result)
        setDraft({ ...EMPTY_DRAFT, ...detail.requirements, template_id: detail.requirements.template_id ?? null })
        setProvider(detail.result.default_provider ?? 'aws')
        setView(detail.result.primary_view ?? 'proposed')
        setProjectId(detail.id)
        setStatus('ready')
        persist(detail.result, draft, options)
        return detail
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'This saved project could not be opened.')
        setStatus('error')
        return null
      }
    },
    [draft, options, persist],
  )

  const saveProject = useCallback(
    async (name?: string) => {
      if (!result) return null
      try {
        const detail = await api.createProject({
          name: (name ?? draft.name ?? result.title).trim() || undefined,
          requirements: result.application,
          options,
          result: result as unknown as Record<string, unknown>,
        })
        setProjectId(detail.id)
        setSavedFlash(detail.id)
        window.setTimeout(() => setSavedFlash(null), 4000)
        await refreshProjects()
        return detail
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'The analysis could not be saved.')
        return null
      }
    },
    [draft.name, options, refreshProjects, result],
  )

  const deleteProject = useCallback(
    async (id: string) => {
      try {
        await api.deleteProject(id)
        if (id === projectId) {
          setProjectId(null)
        }
        await refreshProjects()
      } catch (cause) {
        setProjectsError(cause instanceof Error ? cause.message : 'The project could not be deleted.')
      }
    },
    [projectId, refreshProjects],
  )

  const graph = useMemo(() => {
    if (!result?.architectures?.length) return null
    return result.architectures.find((item) => item.id === view) ?? result.architectures[0] ?? null
  }, [result, view])

  const selectedComponent = useMemo(() => {
    if (!graph || !selectedId) return null
    return graph.components?.find((item) => item.id === selectedId) ?? null
  }, [graph, selectedId])

  const value: NyxValue = {
    meta,
    metaError,
    aiStatus,
    backendOnline,
    draft,
    patchDraft,
    resetDraft,
    applyTemplate,
    options,
    patchOptions,
    status,
    error,
    fieldErrors,
    result,
    run,
    openProject,
    clearResult: () => {
      setResult(null)
      setProjectId(null)
      setStatus('idle')
      setSelectedId(null)
    },
    projectId,
    saveProject,
    savedFlash,
    projects,
    stats,
    projectsError,
    refreshProjects,
    deleteProject,
    provider,
    setProvider,
    view,
    setView,
    graph,
    selectedId,
    select: setSelectedId,
    selectedComponent,
  }

  return <NyxContext.Provider value={value}>{children}</NyxContext.Provider>
}

export function useNyx(): NyxValue {
  const context = useContext(NyxContext)
  if (!context) throw new Error('useNyx must be used inside <NyxProvider>')
  return context
}

/** Options that are only meaningful when the AI layer is actually configured. */
export function useAiAvailability(): { available: boolean; reason: string } {
  const { meta, aiStatus } = useNyx()
  if (meta?.ai.configured) return { available: true, reason: 'An OpenAI-compatible endpoint is configured.' }
  if (aiStatus && aiStatus.status !== 'not_configured') {
    return { available: true, reason: aiStatus.message }
  }
  return {
    available: false,
    reason: meta?.ai.unavailable_reason ?? 'No AI endpoint configured — NYX runs on its deterministic rules engine.',
  }
}
