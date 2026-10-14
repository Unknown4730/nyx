import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, fieldErrorMap, NyxApiError } from '@/lib/api'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('API error envelope', () => {
  it('reads the NYX envelope and keeps field-scoped details', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        json(
          {
            error: {
              code: 'INVALID_REQUEST',
              message: 'The request body did not satisfy the analysis request schema.',
              details: ['requirements.expected_users: Input should be greater than or equal to 1 (greater_than_equal)'],
              retryable: false,
            },
          },
          422,
        ),
      ),
    )
    const error = await api.analyze({ requirements: { name: 'x', description: 'short' }, options: { use_ai: false, providers: ['aws'] } } as never).catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(NyxApiError)
    const failure = error as NyxApiError
    expect(failure.status).toBe(422)
    expect(failure.code).toBe('INVALID_REQUEST')
    expect(failure.isClientError).toBe(true)
    expect(fieldErrorMap(failure.details)).toEqual({
      'requirements.expected_users': 'Input should be greater than or equal to 1 (greater_than_equal)',
    })
  })

  it('maps a network failure to a readable, retryable error without leaking internals', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
    const failure = (await api.meta().catch((cause: unknown) => cause)) as NyxApiError
    expect(failure.status).toBe(0)
    expect(failure.isUnreachable).toBe(true)
    expect(failure.retryable).toBe(true)
    expect(failure.message).toMatch(/cannot reach/i)
    expect(failure.message).not.toMatch(/TypeError|Failed to fetch/)
  })

  it('never shows an HTML gateway page to the user', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('<html>502 Bad Gateway</html>', { status: 502, headers: { 'content-type': 'text/html' } })),
    )
    const failure = (await api.health().catch((cause: unknown) => cause)) as NyxApiError
    expect(failure.status).toBe(502)
    expect(failure.message).not.toMatch(/<html/i)
    expect(failure.code).toBe('api_unreachable')
    expect(failure.isUnreachable).toBe(true)
    expect(failure.message).toMatch(/cannot reach its API/)
  })

  it('reports the Vite dev proxy failure (backend not running) as unreachable, not as a server error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('Error occurred while trying to proxy: localhost:8000/api/meta', { status: 500, headers: { 'content-type': 'text/plain' } })),
    )
    const failure = (await api.meta().catch((cause: unknown) => cause)) as NyxApiError
    expect(failure.code).toBe('api_unreachable')
    expect(failure.isUnreachable).toBe(true)
    expect(failure.message).not.toMatch(/responded with 500/)
  })

  it('treats a silent non-JSON 500 (empty body from the dev proxy) as unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 500, headers: { 'content-type': 'text/plain' } })))
    const failure = (await api.meta().catch((cause: unknown) => cause)) as NyxApiError
    expect(failure.code).toBe('api_unreachable')
    expect(failure.message).not.toMatch(/responded with 500/)
  })

  it('understands a bare FastAPI detail body as a fallback', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'Not Found' }, 404)))
    const failure = (await api.getProject('missing').catch((cause: unknown) => cause)) as NyxApiError
    expect(failure.status).toBe(404)
    expect(failure.message).toBe('Not Found')
  })

  it('reads a project not-found envelope with its code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        json({ error: { code: 'PROJECT_NOT_FOUND', message: 'No saved project exists with that identifier.', details: ["id='x'"], retryable: false } }, 404),
      ),
    )
    const failure = (await api.getProject('x').catch((cause: unknown) => cause)) as NyxApiError
    expect(failure.code).toBe('PROJECT_NOT_FOUND')
    expect(failure.details).toEqual(["id='x'"])
  })
})

describe('export contract', () => {
  it('JSON project export is fetched as an envelope; the content field is the report', async () => {
    const fetchMock = vi.fn(async () =>
      json({ format: 'json', filename: 'nyx-report-abc.json', content: '{"export":{"generator":"NYX"}}' }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const envelope = await api.exportProjectJson('abc')
    expect(fetchMock).toHaveBeenCalledWith('/api/projects/abc/export.json', expect.any(Object))
    expect(envelope.filename).toBe('nyx-report-abc.json')
    expect(JSON.parse(envelope.content)).toEqual({ export: { generator: 'NYX' } })
  })

  it('Markdown project export is returned as text, not parsed as JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('# NYX — Report\n', { status: 200, headers: { 'content-type': 'text/markdown; charset=utf-8' } })),
    )
    await expect(api.exportProjectMarkdown('abc')).resolves.toBe('# NYX — Report\n')
  })
})

describe('fieldErrorMap', () => {
  it('keeps the first message per field and ignores summary lines', () => {
    expect(
      fieldErrorMap(['requirements.name: too short', 'requirements.name: duplicate', '…and 3 further validation issue(s).']),
    ).toEqual({ 'requirements.name': 'too short' })
  })
})
