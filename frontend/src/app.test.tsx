/**
 * Workflow tests: the real App, provider and router, against a fetch double that
 * answers with backend-captured fixtures.  They cover the path a user takes:
 * sample → form → analysis → results → save → export → reopen.
 */
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { errorEnvelope, jsonResponse, mockApi, renderApp, SAMPLE_RESULT } from '@/test/harness'

const ONLINE_TEMPLATE = 'Online Examination Platform'

function requestsTo(calls: { method: string; path: string; body: unknown }[], method: string, path: string) {
  return calls.filter((call) => call.method === method && call.path === path)
}

describe('home and backend status', () => {
  it('shows the product line and an online API once metadata loads', async () => {
    mockApi()
    renderApp('/')
    expect(screen.getByRole('heading', { name: /rethink your/i })).toBeInTheDocument()
    expect(await screen.findByText('API online')).toBeInTheDocument()
    expect(await screen.findByText(/no openai-compatible endpoint/i)).toBeInTheDocument()
  })

  it('says plainly when the API is offline, with no invented numbers', async () => {
    mockApi({ online: false })
    renderApp('/')
    expect(await screen.findByText('API offline')).toBeInTheDocument()
    expect(screen.getByText(/cannot reach its API/i)).toBeInTheDocument()
    expect(screen.queryByText(/stored/i)).not.toBeInTheDocument()
  })

  it('renders an honest not-found page instead of a blank screen', () => {
    mockApi()
    renderApp('/no/such/page')
    expect(screen.getByText(/nothing is running at this address/i)).toBeInTheDocument()
  })
})

describe('analysis workflow', () => {
  it('starts from a sample, runs the analysis and shows the verdict with its evidence', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi()
    renderApp('/analyze')

    await user.click(await screen.findByRole('button', { name: `Use “${ONLINE_TEMPLATE}”` }))
    expect(screen.getByLabelText(/application name/i)).toHaveValue(ONLINE_TEMPLATE)

    await user.click(screen.getByRole('button', { name: /run analysis/i }))

    const sent = requestsTo(calls, 'POST', '/api/analyze')
    expect(sent).toHaveLength(1)
    expect((sent[0].body as { requirements: { name: string } }).requirements.name).toBe(ONLINE_TEMPLATE)

    const headline = String((SAMPLE_RESULT.suitability as { headline: string }).headline)
    expect(await screen.findByRole('heading', { name: headline })).toBeInTheDocument()
    // The verdict label is shown in the header and the overview; both must agree with the API outcome.
    expect(screen.getAllByText(/strong candidate/i).length).toBeGreaterThan(0)
    expect(screen.getByText('How the score was built')).toBeInTheDocument()
  })

  it('does not send an obviously invalid form, and focuses the first problem', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi()
    renderApp('/analyze')
    await screen.findByRole('button', { name: /run analysis/i })
    await user.click(screen.getByRole('button', { name: /run analysis/i }))
    expect(await screen.findByText(/give the application a name of at least 2 characters/i)).toBeInTheDocument()
    expect(screen.getByText(/describe the application in at least 10 characters/i)).toBeInTheDocument()
    expect(requestsTo(calls, 'POST', '/api/analyze')).toHaveLength(0)
  })

  it('maps a backend validation error onto the field it belongs to', async () => {
    const user = userEvent.setup()
    mockApi({
      analyzeResponse: () =>
        errorEnvelope(422, 'INVALID_REQUEST', 'The request body did not satisfy the analysis request schema.', [
          'requirements.expected_users: Input should be greater than or equal to 1 (greater_than_equal)',
        ]),
    })
    renderApp('/analyze')
    await user.type(await screen.findByLabelText(/application name/i), 'Campus portal')
    await user.type(screen.getByLabelText(/^description/i), 'A campus portal for staff and students.')
    await user.click(screen.getByRole('button', { name: /run analysis/i }))
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(/the analysis did not run/i)).toBeInTheDocument()
    expect(within(alert).getByText(/greater than or equal to 1/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/expected users/i)).toHaveAttribute('aria-invalid', 'true')
  })

  it('shows a readable message, not a stack trace, when the API is down during a run', async () => {
    const user = userEvent.setup()
    mockApi({ analyzeResponse: () => jsonResponse({}, 500) })
    renderApp('/analyze')
    await user.type(await screen.findByLabelText(/application name/i), 'Campus portal')
    await user.type(screen.getByLabelText(/^description/i), 'A campus portal for staff and students.')
    await user.click(screen.getByRole('button', { name: /run analysis/i }))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent ?? '').not.toMatch(/Error:|at \w+\.|stack/i)
  })
})

describe('results', () => {
  async function openResults(user: ReturnType<typeof userEvent.setup>) {
    renderApp('/analyze')
    await user.click(await screen.findByRole('button', { name: `Use “${ONLINE_TEMPLATE}”` }))
    await user.click(screen.getByRole('button', { name: /run analysis/i }))
    await screen.findByRole('tablist', { name: /result sections/i })
  }

  it('moves between sections with the keyboard and draws the proposed architecture from real data', async () => {
    const user = userEvent.setup()
    mockApi()
    await openResults(user)

    const tabs = screen.getAllByRole('tab')
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
    tabs[0].focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Architecture' })).toHaveAttribute('aria-selected', 'true')

    const nodes = await screen.findAllByTestId('diagram-node')
    const proposed = (SAMPLE_RESULT.architectures as { id: string; components: unknown[] }[]).find((graph) => graph.id === 'proposed')
    expect(nodes).toHaveLength(proposed?.components.length ?? -1)

    const firstNode = nodes[0]
    fireEvent.click(firstNode)
    const inspector = await screen.findByTestId('inspector')
    expect(within(inspector).getByRole('heading', { level: 3 })).toHaveTextContent(firstNode.getAttribute('aria-label')?.split('.')[0] ?? '')
  })

  it('shows the Current and Proposed blueprints as separate views', async () => {
    const user = userEvent.setup()
    mockApi()
    await openResults(user)
    await user.click(screen.getByRole('tab', { name: 'Architecture' }))
    await user.click(await screen.findByRole('tab', { name: /current \(serverful\)/i }))
    const diagram = await screen.findByTestId('architecture-svg')
    expect(diagram).toHaveAttribute('aria-label', expect.stringMatching(/components/))
  })

  it('zoom steps through the readable scales and stops at both ends', async () => {
    const user = userEvent.setup()
    mockApi()
    await openResults(user)
    await user.click(screen.getByRole('tab', { name: 'Architecture' }))
    await screen.findByTestId('architecture-svg')
    expect(screen.getByText('100%')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(screen.getByText('80%')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(screen.getByText('60%')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(screen.getByText('40%')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zoom out' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(screen.getByText('60%')).toBeInTheDocument()
  })

  it('Reset returns the diagram to the readable 100% scale, and Fit never leaves the scale range', async () => {
    const user = userEvent.setup()
    mockApi()
    await openResults(user)
    await user.click(screen.getByRole('tab', { name: 'Architecture' }))
    await screen.findByTestId('architecture-svg')
    await user.click(screen.getByRole('button', { name: 'Zoom out' }))
    await user.click(screen.getByRole('button', { name: 'Reset' }))
    expect(screen.getByText('100%')).toBeInTheDocument()
    // jsdom has no layout, so the viewport width is 0 and Fit falls back to the readable default.
    await user.click(screen.getByRole('button', { name: 'Fit to width' }))
    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('shows every cost sensitivity row, including scenarios that share a driver name', async () => {
    const user = userEvent.setup()
    mockApi()
    await openResults(user)
    await user.click(screen.getByRole('tab', { name: 'Cost model' }))
    const sensitivity = await screen.findByRole('table', { name: /sensitivity of the cost comparison/i })
    const sample = (SAMPLE_RESULT.cost as { sensitivity: { low_label: string }[] }).sensitivity
    const rows = within(sensitivity).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(sample.length)
    for (const entry of sample) {
      expect(within(sensitivity).getByText(entry.low_label)).toBeInTheDocument()
    }
  })

  it('selecting a component shows its details in the inspector', async () => {
    const user = userEvent.setup()
    mockApi()
    await openResults(user)
    await user.click(screen.getByRole('tab', { name: 'Architecture' }))
    const node = (await screen.findAllByTestId('diagram-node'))[0]
    await user.click(node)
    expect(await screen.findByTestId('inspector')).toBeInTheDocument()
  })

  it('saves the analysis as a project and says so', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi()
    await openResults(user)
    await user.click(screen.getByRole('button', { name: /save project/i }))
    await waitFor(() => expect(requestsTo(calls, 'POST', '/api/projects')).toHaveLength(1))
    expect(await screen.findByText(/saved as/i)).toBeInTheDocument()
    expect(screen.getByText('Saved to projects')).toBeInTheDocument()
  })

  it('exports an unsaved deterministic result by re-running the rules with AI switched off', async () => {
    const user = userEvent.setup()
    const createObjectURL = vi.fn(() => 'blob:nyx')
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }))
    const { calls } = mockApi()
    await openResults(user)
    await user.click(screen.getByRole('button', { name: /export json/i }))
    await waitFor(() => expect(requestsTo(calls, 'POST', '/api/analyze/export')).toHaveLength(1))
    const sent = requestsTo(calls, 'POST', '/api/analyze/export')[0].body as { format: string; options: { use_ai: boolean } }
    expect(sent.format).toBe('json')
    expect(sent.options.use_ai).toBe(false)
    expect(await screen.findByText(/json report downloaded/i)).toBeInTheDocument()
  })

  it('exports a saved project from its stored copy, not a fresh run', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:nyx'), revokeObjectURL: vi.fn() }))
    const { calls } = mockApi({ projects: [] })
    await openResults(user)
    await user.click(screen.getByRole('button', { name: /save project/i }))
    await screen.findByText('Saved to projects')
    await user.click(screen.getByRole('button', { name: /export markdown/i }))
    await waitFor(() => expect(calls.some((call) => call.path.endsWith('/report.md'))).toBe(true))
    expect(requestsTo(calls, 'POST', '/api/analyze/export')).toHaveLength(0)
  })
})

describe('projects', () => {
  const summary = {
    id: 'proj-1',
    name: 'Campus portal',
    kind: 'user_project',
    engine_mode: 'deterministic_rules',
    application_type: 'web_app',
    suitability_score: 78.1,
    suitability_outcome: 'strong_candidate',
    component_count: 11,
    finding_count: 0,
    created_at: '2026-10-11T12:00:00+00:00',
    updated_at: '2026-10-11T12:00:00+00:00',
    excerpt: '',
  }
  const sample = { ...summary, id: 'example-1', name: 'Built-in example', kind: 'example_project' }

  it('lists saved projects and labels samples as samples', async () => {
    mockApi({ projects: [summary, sample] })
    renderApp('/projects')
    expect(await screen.findByText('Campus portal')).toBeInTheDocument()
    expect(screen.getByText('Built-in example')).toBeInTheDocument()
    expect(screen.getByText('Sample')).toBeInTheDocument()
  })

  it('shows an honest empty state when nothing is saved', async () => {
    mockApi({ projects: [] })
    renderApp('/projects')
    expect(await screen.findByText(/no saved projects yet/i)).toBeInTheDocument()
  })

  it('reopens a saved project and shows the same result', async () => {
    const user = userEvent.setup()
    mockApi({ projects: [summary] })
    renderApp('/projects')
    await user.click(await screen.findByRole('button', { name: 'Open' }))
    const headline = String((SAMPLE_RESULT.suitability as { headline: string }).headline)
    expect(await screen.findByRole('heading', { name: headline })).toBeInTheDocument()
  })

  it('reports a missing project with the API message and a way back', async () => {
    mockApi()
    renderApp('/projects/missing')
    expect(await screen.findByRole('alert')).toHaveTextContent(/no saved project exists/i)
    expect(screen.getByRole('link', { name: /back to projects/i })).toBeInTheDocument()
  })

  it('asks before deleting a project', async () => {
    const user = userEvent.setup()
    mockApi({ projects: [summary] })
    renderApp('/projects')
    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    expect(screen.getByRole('button', { name: /confirm delete/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(screen.queryByRole('button', { name: /confirm delete/i })).not.toBeInTheDocument()
  })
})

describe('method page', () => {
  it('reads the scoring bands and limits from the API rather than hard-coding them', async () => {
    mockApi()
    renderApp('/method')
    expect(await screen.findByRole('heading', { name: 'Score bands' })).toBeInTheDocument()
    expect(await screen.findByText(/share of workload weight without/i)).toBeInTheDocument()
  })
})
