import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ArchitectureDiagram, clip, computeLayout, edgePath, NODE_HEIGHT, NODE_WIDTH, wrapLines } from '@/components/ArchitectureDiagram'
import type { ArchitectureGraph } from '@/types/analysis'
import sample from '@/test/fixtures/sample-analysis.json'

const proposed = (sample.architectures as unknown as ArchitectureGraph[]).find((graph) => graph.id === 'proposed') as ArchitectureGraph

describe('computeLayout', () => {
  it('places every node inside the canvas with the same padding on each side', () => {
    const layout = computeLayout(proposed)
    const positions = Object.values(layout.positions)
    expect(positions).toHaveLength(proposed.components?.length ?? -1)
    for (const point of positions) {
      expect(point.x).toBeGreaterThanOrEqual(48)
      expect(point.y).toBeGreaterThanOrEqual(48)
      expect(point.x + NODE_WIDTH).toBeLessThanOrEqual(layout.width)
      expect(point.y + NODE_HEIGHT).toBeLessThanOrEqual(layout.height)
    }
  })

  it('uses the backend coordinates, shifted but not rescaled', () => {
    const layout = computeLayout(proposed)
    const raw = proposed.layout ?? {}
    const ids = Object.keys(raw)
    const xs = ids.map((id) => raw[id]?.x ?? Infinity)
    const minX = Math.min(...xs)
    const first = ids[0]
    const origin = layout.positions[first]
    expect(origin).toBeDefined()
    expect(origin?.x).toBeCloseTo((raw[first]?.x ?? NaN) - minX + 48, 5)
  })

  it('still draws a component the layout forgot, rather than dropping it', () => {
    const graph: ArchitectureGraph = {
      id: 'x',
      style: 'serverless',
      title: 't',
      components: [
        { id: 'a', label: 'A', type: 'client_web', tier: 'edge' },
        { id: 'b', label: 'B', type: 'client_web', tier: 'edge' },
      ],
      layout: { a: { x: 10, y: 10 } },
    } as unknown as ArchitectureGraph
    const layout = computeLayout(graph)
    expect(Object.keys(layout.positions).sort()).toEqual(['a', 'b'])
  })

  it('returns an empty canvas for an empty graph', () => {
    expect(computeLayout({ id: 'e', style: 'serverless', title: 'e', components: [] } as unknown as ArchitectureGraph)).toEqual({
      width: 0,
      height: 0,
      positions: {},
    })
  })
})

describe('edgePath', () => {
  it('leaves the right edge and enters the left edge when the target is to the right', () => {
    const { d } = edgePath({ x: 0, y: 0 }, { x: 400, y: 0 })
    expect(d.startsWith(`M ${NODE_WIDTH} ${NODE_HEIGHT / 2}`)).toBe(true)
    expect(d.endsWith(`400 ${NODE_HEIGHT / 2}`)).toBe(true)
  })

  it('leaves the bottom edge when the target sits below', () => {
    const { d } = edgePath({ x: 0, y: 0 }, { x: 0, y: 300 })
    expect(d.startsWith(`M ${NODE_WIDTH / 2} ${NODE_HEIGHT}`)).toBe(true)
  })

  it('returns a midpoint between the two nodes', () => {
    const { mid } = edgePath({ x: 0, y: 0 }, { x: 400, y: 0 })
    expect(mid.x).toBeGreaterThan(NODE_WIDTH)
    expect(mid.x).toBeLessThan(400)
  })
})

describe('clip', () => {
  it('leaves short text alone and ellipsises long text within the limit', () => {
    expect(clip('Short', 10)).toBe('Short')
    const clipped = clip('A very long component label indeed', 12)
    expect(clipped.endsWith('…')).toBe(true)
    expect(clipped.length).toBeLessThanOrEqual(12)
  })
})

describe('ArchitectureDiagram rendering', () => {
  it('renders one accessible control per component and reports selection', () => {
    const onSelect = vi.fn()
    render(<ArchitectureDiagram graph={proposed} provider="aws" selectedId={null} onSelect={onSelect} idPrefix="t" />)
    const nodes = screen.getAllByTestId('diagram-node')
    expect(nodes).toHaveLength(proposed.components?.length ?? -1)
    expect(nodes[0]).toHaveAttribute('role', 'button')
    expect(nodes[0]).toHaveAttribute('tabindex', '0')

    fireEvent.keyDown(nodes[1], { key: 'Enter' })
    expect(onSelect).toHaveBeenLastCalledWith(nodes[1].getAttribute('data-node-id'))
    fireEvent.keyDown(nodes[2], { key: ' ' })
    expect(onSelect).toHaveBeenLastCalledWith(nodes[2].getAttribute('data-node-id'))
  })

  it('draws every trust boundary and connection the graph declares', () => {
    const { container } = render(<ArchitectureDiagram graph={proposed} provider="gcp" selectedId="client" onSelect={() => undefined} idPrefix="t" />)
    expect(screen.getAllByTestId('trust-boundary')).toHaveLength(proposed.trust_boundaries?.length ?? 0)
    expect(screen.getAllByTestId('connection')).toHaveLength(proposed.connections?.length ?? 0)
    expect(container.querySelector('[data-node-id="client"]')).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('wrapLines', () => {
  it('keeps a long label whole across two lines instead of cutting it', () => {
    const lines = wrapLines('Managed API surface (routes and throttling)', 26, 2)
    expect(lines).toEqual(['Managed API surface', '(routes and throttling)'])
    expect(lines.join(' ')).not.toMatch(/…/)
  })

  it('only shortens text that still does not fit after the allowed lines', () => {
    const lines = wrapLines('one two three four five six seven eight nine ten eleven twelve', 20, 2)
    expect(lines).toHaveLength(2)
    expect(lines.every((line) => line.length <= 20)).toBe(true)
    expect(lines[1].endsWith('…')).toBe(true)
  })

  it('leaves a short label on one line', () => {
    expect(wrapLines('Edge CDN', 26, 2)).toEqual(['Edge CDN'])
  })
})
