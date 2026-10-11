/**
 * Test harness: a route-aware fetch double and a render helper that mounts the real
 * App inside the real session provider and router.  Responses come from fixtures
 * captured from the backend (see test/fixtures), not from hand-written results.
 */
import { render } from '@testing-library/react'
import { vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import { App } from '@/App'
import { NyxProvider } from '@/state/NyxProvider'

import meta from './fixtures/meta.json'
import sampleResult from './fixtures/sample-analysis.json'

export const SAMPLE_RESULT = sampleResult as Record<string, unknown>
export const META = meta

export interface MockOptions {
  online?: boolean
  projects?: Record<string, unknown>[]
  analyzeResponse?: () => Response
  projectDetail?: (id: string) => Response
  exportEnvelope?: (format: string) => Response
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

export function errorEnvelope(status: number, code: string, message: string, details: string[] = []): Response {
  return jsonResponse({ error: { code, message, details, retryable: status >= 500 } }, status)
}

const HEALTH = {
  status: 'ok',
  service: 'NYX',
  title: 'AI-Assisted Serverless Migration and Cloud Architecture Advisor',
  tagline: 'Rethink your architecture.',
  version: '1.0.0',
  schema_version: 'nyx.analysis/1',
  engine_mode: 'deterministic_rules',
  ai: {},
  storage: {},
  timestamp: '2026-10-11T12:00:00+00:00',
}

/** Install a fetch double that answers each NYX endpoint the way the real API does. */
export function mockApi(options: MockOptions = {}) {
  const online = options.online ?? true
  const projects = options.projects ?? []
  const calls: { method: string; path: string; body: unknown }[] = []

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const path = url.replace(/^https?:\/\/[^/]+/, '')
    const method = (init?.method ?? 'GET').toUpperCase()
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ method, path, body })

    if (!online) throw new TypeError('Failed to fetch')

    if (path === '/api/meta') return jsonResponse(META)
    if (path === '/api/health') return jsonResponse(HEALTH)
    if (path === '/api/ai/status') return jsonResponse({ status: 'not_configured', message: 'No OpenAI-compatible endpoint is configured. Deterministic analysis is fully available.' })
    if (path === '/api/projects/stats') {
      return jsonResponse({
        total: projects.length,
        user_projects: projects.filter((item) => item.kind === 'user_project').length,
        example_projects: projects.filter((item) => item.kind === 'example_project').length,
        newest: null,
        oldest: null,
        outcomes: {},
        application_types: {},
        average_user_score: null,
        recent: projects.slice(0, 6),
      })
    }
    if (path.startsWith('/api/projects?') || path === '/api/projects') {
      if (method === 'POST') {
        const detail = { id: 'proj-new', name: body?.name ?? 'Saved', kind: 'user_project', created_at: '2026-10-11T12:00:00+00:00', updated_at: '2026-10-11T12:00:00+00:00', requirements: body?.requirements, result: SAMPLE_RESULT }
        return jsonResponse(detail, 201)
      }
      return jsonResponse(projects)
    }
    const exportMatch = path.match(/^\/api\/projects\/([^/]+)\/export\.json$/)
    if (exportMatch) {
      return jsonResponse({ format: 'json', filename: `nyx-report-${exportMatch[1]}.json`, content: JSON.stringify(SAMPLE_RESULT) })
    }
    const markdownMatch = path.match(/^\/api\/projects\/([^/]+)\/report\.md$/)
    if (markdownMatch) {
      return new Response('# NYX — Report\n', { status: 200, headers: { 'content-type': 'text/markdown; charset=utf-8' } })
    }
    const projectMatch = path.match(/^\/api\/projects\/([^/]+)$/)
    if (projectMatch) {
      if (options.projectDetail) return options.projectDetail(projectMatch[1])
      if (projectMatch[1] === 'missing') return errorEnvelope(404, 'PROJECT_NOT_FOUND', 'No saved project exists with that identifier.', ["id='missing'"])
      return jsonResponse({ id: projectMatch[1], name: 'Saved analysis', kind: 'user_project', created_at: '2026-10-11T12:00:00+00:00', updated_at: '2026-10-11T12:00:00+00:00', requirements: SAMPLE_RESULT.application, result: SAMPLE_RESULT })
    }
    if (path === '/api/analyze' && method === 'POST') {
      return options.analyzeResponse ? options.analyzeResponse() : jsonResponse(SAMPLE_RESULT)
    }
    if (path === '/api/analyze/export' && method === 'POST') {
      const format = String(body?.format ?? 'json')
      return options.exportEnvelope
        ? options.exportEnvelope(format)
        : jsonResponse({ format, filename: `nyx-report-test.${format === 'markdown' ? 'md' : 'json'}`, content: format === 'markdown' ? '# report' : '{}' })
    }
    return jsonResponse({ detail: 'Not Found' }, 404)
  })

  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, calls }
}

export function renderApp(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <NyxProvider>
        <App />
      </NyxProvider>
    </MemoryRouter>,
  )
}
