/**
 * Typed client for the NYX API.
 *
 * Every call is same-origin (`/api/...`) so the browser never needs to know
 * where the backend lives: vite proxies it in development and the backend serves
 * the built assets in production.  Failures are normalised into one shape so the
 * UI can distinguish "the engine rejected my input" from "the service is down".
 */
import type {
  AnalysisRequest,
  AnalysisResult,
  HealthResponse,
  ProjectCreateRequest,
  ProjectDetail,
  ProjectSummary,
  ProjectUpdateRequest,
} from '@/types/analysis'
// `AnalysisExportRequest` is not emitted by the schema generator yet, so it lives
// with the other hand-written contract types (see the approval request in the
// Cycle 0a report).  Everything else here comes from the generated contract.
import type { AiStatus, AnalysisExportRequest, ExportFormat, MetaPayload, ProjectStats } from '@/types/nyx'

export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''

/**
 * One failure shape for the whole client, built from the NYX error envelope:
 * `{ error: { code, message, details, retryable } }` (`backend/app/api/errors.py`).
 */
export class NyxApiError extends Error {
  readonly status: number
  readonly code: string
  /** Human-readable issues from `error.details`; empty when the API sent none. */
  readonly details: string[]
  /** `error.retryable`: the API says attempting the request again may succeed. */
  readonly retryable: boolean

  constructor(init: { status: number; code: string; message: string; details?: string[]; retryable?: boolean }) {
    super(init.message)
    this.name = 'NyxApiError'
    this.status = init.status
    this.code = init.code
    this.details = init.details ?? []
    this.retryable = init.retryable ?? false
  }

  /** 4xx means the user can fix it; 5xx/network means the service must be checked. */
  get isClientError(): boolean {
    return this.status >= 400 && this.status < 500
  }

  /** True when the API supplied at least one readable detail (usually validation). */
  get hasDetails(): boolean {
    return this.details.length > 0
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
    let parsed: ParsedApiError | null = null
    if (contentType.includes('json')) {
      parsed = readErrorEnvelope(await response.json().catch(() => null))
    } else {
      // A proxy or gateway error page: keep one short readable line, never HTML.
      const text = (await response.text().catch(() => '')).trim()
      if (text && !text.startsWith('<')) {
        parsed = { code: 'http_error', message: text.slice(0, 240), details: [], retryable: false }
      }
    }
    throw new NyxApiError({
      status: response.status,
      code: parsed?.code ?? 'http_error',
      message: parsed?.message ?? `The API responded with ${response.status}.`,
      details: parsed?.details,
      retryable: parsed?.retryable,
    })
  }

  if (response.status === 204 || contentType.includes('json') === false) {
    return undefined as T
  }
  return (await response.json()) as T
}

/** The parts of the NYX error envelope this client reads. */
interface ParsedApiError {
  code: string
  message: string
  details: string[]
  retryable: boolean
}

/**
 * `error.details` is `string[]` in the NYX envelope.  FastAPI-style `{loc, msg}`
 * entries are still flattened so a proxy or an older build cannot crash the UI.
 */
function toDetailStrings(value: unknown): string[] {
  if (typeof value === 'string') return value.trim() ? [value.trim()] : []
  if (!Array.isArray(value)) return []
  const out: string[] = []
  for (const item of value) {
    if (typeof item === 'string') {
      if (item.trim()) out.push(item.trim())
      continue
    }
    const entry = item as { loc?: (string | number)[]; msg?: string } | null
    const where = (entry?.loc ?? []).filter((segment) => segment !== 'body').join('.')
    const message = entry?.msg ?? 'invalid value'
    out.push(where ? `${where}: ${message}` : message)
  }
  return out
}

/**
 * Read the error envelope produced by `backend/app/api/errors.py`:
 *
 *     { "error": { "code": ..., "message": ..., "details": string[], "retryable": bool } }
 *
 * Every NYX failure — validation, not-found, unexpected — uses this shape, so the
 * readable, field-scoped messages are in `error.details`.  A bare FastAPI
 * `{ "detail": ... }` body is understood as a fallback, and anything else returns
 * `null` instead of throwing.
 */
function readErrorEnvelope(body: unknown): ParsedApiError | null {
  if (!body || typeof body !== 'object') return null

  const wrapped = (body as { error?: unknown }).error
  if (wrapped && typeof wrapped === 'object') {
    const envelope = wrapped as { code?: unknown; message?: unknown; details?: unknown; retryable?: unknown }
    return {
      code: typeof envelope.code === 'string' && envelope.code ? envelope.code : 'http_error',
      message:
        typeof envelope.message === 'string' && envelope.message
          ? envelope.message
          : 'The API reported an error without a message.',
      details: toDetailStrings(envelope.details),
      retryable: envelope.retryable === true,
    }
  }

  const bare = (body as { detail?: unknown }).detail
  if (bare === undefined) return null
  const details = toDetailStrings(bare)
  return {
    code: 'http_error',
    message: typeof bare === 'string' && bare ? bare : (details[0] ?? 'The request was rejected.'),
    details,
    retryable: false,
  }
}

/** Field paths in `details` look like `requirements.expected_users` or `options.providers.0`. */
const FIELD_PATH = /^[A-Za-z0-9_.[\]]+$/

/**
 * Split `"<field path>: <message>"` details into a field → message map so a form
 * can render each message next to its control.  Entries without a field path (such
 * as the trailing "…and N further…" summary) are left on `NyxApiError.details`.
 */
export function fieldErrorMap(details: readonly string[]): Record<string, string> {
  const map: Record<string, string> = {}
  for (const entry of details) {
    const separator = entry.indexOf(': ')
    if (separator <= 0) continue
    const field = entry.slice(0, separator).trim()
    const message = entry.slice(separator + 2).trim()
    if (message && FIELD_PATH.test(field) && !(field in map)) map[field] = message
  }
  return map
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

  /** `POST /api/analyze/export` renders the report inline and returns it directly. */
  exportResult: (payload: AnalysisExportRequest) =>
    request<{ format: ExportFormat; filename: string; content: string }>('/api/analyze/export', {
      method: 'POST',
      headers: json,
      body: JSON.stringify(payload),
      timeoutMs: 60_000,
    }),

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
