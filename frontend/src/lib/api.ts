/**
 * Typed client for the NYX API.
 *
 * Every call is same-origin (`/api/...`) so the browser never needs to know
 * where the backend lives: vite proxies it in development and the backend serves
 * the built assets in production.  Failures are normalised into one shape so the
 * UI can distinguish "the engine rejected my input" from "the service is down".
 */
import type {
  AnalysisExportRequest,
  AnalysisRequest,
  AnalysisResult,
  HealthResponse,
  ProjectCreateRequest,
  ProjectDetail,
  ProjectSummary,
  ProjectUpdateRequest,
} from '@/types/analysis'
import type { AiStatus, MetaPayload, ProjectStats } from '@/types/nyx'

export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''

export class NyxApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: unknown
  readonly requestId: string | null

  constructor(init: { status: number; code: string; message: string; detail?: unknown; requestId?: string | null }) {
    super(init.message)
    this.name = 'NyxApiError'
    this.status = init.status
    this.code = init.code
    this.detail = init.detail
    this.requestId = init.requestId ?? null
  }

  /** 4xx means the user can fix it; 5xx/network means the service must be checked. */
  get isClientError(): boolean {
    return this.status >= 400 && this.status < 500
  }
}

type Init = RequestInit & { timeoutMs?: number }

async function request<T>(path: string, init: Init = {}): Promise<T> {
  const { timeoutMs = 30_000, headers, ...rest } = init
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: { Accept: 'application/json', ...(headers ?? {}) },
      signal: controller.signal,
    })
  } catch (error) {
    clearTimeout(timer)
    const aborted = error instanceof DOMException && error.name === 'AbortError'
    throw new NyxApiError({
      status: aborted ? 408 : 0,
      code: aborted ? 'client_timeout' : 'network_error',
      message: aborted
        ? 'The backend did not answer in time. The analysis usually takes under a second, so the service may not be running.'
        : 'Cannot reach the NYX API. Start the backend (uvicorn app.main:app) or set VITE_API_BASE_URL.',
    })
  }
  clearTimeout(timer)

  const contentType = response.headers.get('content-type') ?? ''
  if (!response.ok) {
    let code = 'http_error'
    let message = `The API responded with ${response.status}.`
    let detail: unknown = null
    let requestId: string | null = response.headers.get('x-request-id')
    if (contentType.includes('json')) {
      const body = (await response.json().catch(() => null)) as
        | { error?: { code?: string; message?: string; detail?: unknown; request_id?: string } }
        | { detail?: unknown }
        | null
      const wrapped = (body as { error?: Record<string, unknown> } | null)?.error
      if (wrapped) {
        code = String(wrapped.code ?? code)
        message = String(wrapped.message ?? message)
        detail = wrapped.detail
        requestId = (wrapped.request_id as string) ?? requestId
      } else if ((body as { detail?: unknown } | null)?.detail !== undefined) {
        detail = (body as { detail: unknown }).detail
        message = typeof detail === 'string' ? detail : fastapiMessage(detail) ?? message
      }
    } else {
      message = (await response.text().catch(() => '')).slice(0, 240) || message
    }
    throw new NyxApiError({ status: response.status, code, message, detail, requestId })
  }

  if (response.status === 204 || contentType.includes('json') === false) {
    return undefined as T
  }
  return (await response.json()) as T
}

/** FastAPI's validation errors arrive as `detail: [{loc, msg, type}]`. */
function fastapiMessage(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) return null
  const parts = detail.map((item) => {
    const entry = item as { loc?: (string | number)[]; msg?: string }
    const where = (entry.loc ?? []).filter((segment) => segment !== 'body').join('.')
    return where ? `${where}: ${entry.msg ?? 'invalid'}` : (entry.msg ?? 'invalid value')
  })
  return `The API rejected the request — ${parts.join('; ')}`
}

const json = { 'Content-Type': 'application/json' }

export const api = {
  health: () => request<HealthResponse>('/api/health'),
  meta: () => request<MetaPayload>('/api/meta'),
  aiStatus: () => request<AiStatus>('/api/ai/status'),

  analyze: (payload: AnalysisRequest) =>
    request<AnalysisResult>('/api/analyze', {
      method: 'POST',
      headers: json,
      body: JSON.stringify(payload),
      timeoutMs: 60_000,
    }),

  exportResult: (payload: AnalysisExportRequest) =>
    request<{ format: string; filename: string; content: string; export: Record<string, unknown> }>(
      '/api/analyze/export',
      { method: 'POST', headers: json, body: JSON.stringify(payload), timeoutMs: 60_000 },
    ),

  listProjects: (limit = 50, offset = 0) =>
    request<ProjectSummary[]>(`/api/projects?limit=${limit}&offset=${offset}`),
  projectStats: () => request<ProjectStats>('/api/projects/stats'),
  getProject: (id: string) => request<ProjectDetail>(`/api/projects/${encodeURIComponent(id)}`),
  createProject: (payload: ProjectCreateRequest) =>
    request<ProjectDetail>('/api/projects', { method: 'POST', headers: json, body: JSON.stringify(payload) }),
  updateProject: (id: string, payload: ProjectUpdateRequest) =>
    request<ProjectDetail>(`/api/projects/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: json,
      body: JSON.stringify(payload),
    }),
  deleteProject: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/api/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

/** Direct download links (the browser handles these, so no fetch/JSON round trip). */
export const downloadUrls = {
  projectJson: (id: string) => `${API_BASE}/api/projects/${encodeURIComponent(id)}/export.json`,
  projectMarkdown: (id: string) => `${API_BASE}/api/projects/${encodeURIComponent(id)}/report.md`,
}

/** Save a server-rendered text payload as a file without any extra dependency. */
export function saveTextFile(filename: string, content: string, mime = 'application/json') {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Revoking immediately can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}
