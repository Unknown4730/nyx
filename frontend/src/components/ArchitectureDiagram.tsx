/**
 * Architecture diagram rendered from the analysis graph.
 *
 * Node positions come from the backend layout (`graph.layout`), so the picture is
 * the same one the API describes; nothing is positioned or invented here.  The SVG
 * uses solid fills and strokes only.  Keyboard users can reach every node, and the
 * same content is repeated as a text list by the workspace.
 */
import { useMemo } from 'react'

import { DEPLOYMENT_LABEL, DIAGRAM_COLOUR as C, TIER_ACCENT, TIER_LABELS } from '@/lib/tone'
import { humanise } from '@/lib/format'
import type { ArchitectureGraph, CloudProvider, Component, Connection } from '@/types/analysis'

export const NODE_WIDTH = 236
export const NODE_HEIGHT = 92
const PADDING = 48

interface Point {
  x: number
  y: number
}

export interface DiagramLayout {
  width: number
  height: number
  positions: Record<string, Point>
}

/**
 * Compute the canvas size and node origins.  Backend coordinates are shifted so the
 * left-most and top-most node sit at the padding; a node the layout does not place is
 * put on a simple row so nothing silently disappears.
 */
export function computeLayout(graph: ArchitectureGraph): DiagramLayout {
  const components = graph.components ?? []
  const raw: Record<string, Point> = {}
  components.forEach((component, index) => {
    const placed = graph.layout?.[component.id]
    raw[component.id] = placed
      ? { x: Number(placed.x), y: Number(placed.y) }
      : { x: index * (NODE_WIDTH + 48), y: 0 }
  })
  const points = Object.values(raw)
  if (points.length === 0) return { width: 0, height: 0, positions: {} }
  const minX = Math.min(...points.map((p) => p.x))
  const minY = Math.min(...points.map((p) => p.y))
  const maxX = Math.max(...points.map((p) => p.x))
  const maxY = Math.max(...points.map((p) => p.y))
  const positions: Record<string, Point> = {}
  for (const [id, point] of Object.entries(raw)) {
    positions[id] = { x: point.x - minX + PADDING, y: point.y - minY + PADDING }
  }
  return {
    width: maxX - minX + NODE_WIDTH + PADDING * 2,
    height: maxY - minY + NODE_HEIGHT + PADDING * 2,
    positions,
  }
}

/** Anchor points and a cubic path between two node boxes. */
export function edgePath(from: Point, to: Point): { d: string; mid: Point } {
  const fromCenter = { x: from.x + NODE_WIDTH / 2, y: from.y + NODE_HEIGHT / 2 }
  const toCenter = { x: to.x + NODE_WIDTH / 2, y: to.y + NODE_HEIGHT / 2 }
  let start: Point
  let end: Point
  let c1: Point
  let c2: Point
  if (to.x >= from.x + NODE_WIDTH) {
    // Target sits to the right: leave the right edge, enter the left edge.
    start = { x: from.x + NODE_WIDTH, y: fromCenter.y }
    end = { x: to.x, y: toCenter.y }
    const dx = (end.x - start.x) / 2
    c1 = { x: start.x + dx, y: start.y }
    c2 = { x: end.x - dx, y: end.y }
  } else if (from.x >= to.x + NODE_WIDTH) {
    // Target sits to the left: leave the left edge, enter the right edge.
    start = { x: from.x, y: fromCenter.y }
    end = { x: to.x + NODE_WIDTH, y: toCenter.y }
    const dx = (start.x - end.x) / 2
    c1 = { x: start.x - dx, y: start.y }
    c2 = { x: end.x + dx, y: end.y }
  } else {
    // Stacked vertically: leave bottom/top centre.
    const downwards = to.y >= from.y
    start = { x: fromCenter.x, y: downwards ? from.y + NODE_HEIGHT : from.y }
    end = { x: toCenter.x, y: downwards ? to.y : to.y + NODE_HEIGHT }
    const dy = (end.y - start.y) / 2
    c1 = { x: start.x, y: start.y + dy }
    c2 = { x: end.x, y: end.y - dy }
  }
  const d = `M ${start.x} ${start.y} C ${c1.x} ${c1.y} ${c2.x} ${c2.y} ${end.x} ${end.y}`
  const mid = {
    x: (start.x + 3 * c1.x + 3 * c2.x + end.x) / 8,
    y: (start.y + 3 * c1.y + 3 * c2.y + end.y) / 8,
  }
  return { d, mid }
}

/** Shorten text for an SVG label; the full text is kept in a `<title>`. */
export function clip(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…`
}

function serviceFor(component: Component, provider: CloudProvider): string | null {
  const mapping = component.mappings?.[provider]
  return mapping?.service_name ?? null
}

function connectionStyle(connection: Connection): { dash?: string; stroke: string; opacity: number } {
  if (connection.crosses_trust_boundary) return { stroke: C.trustBoundary, opacity: 0.9, dash: undefined }
  if (connection.async_delivery) return { stroke: C.asyncConnection, opacity: 0.9, dash: '7 5' }
  if (connection.optional) return { stroke: C.optionalConnection, opacity: 0.75, dash: '2 4' }
  return { stroke: C.connection, opacity: 0.7 }
}

export function ArchitectureDiagram({
  graph,
  provider,
  selectedId,
  onSelect,
  zoom = 1,
  idPrefix,
}: {
  graph: ArchitectureGraph
  provider: CloudProvider
  selectedId: string | null
  onSelect: (id: string) => void
  zoom?: number
  idPrefix: string
}) {
  const layout = useMemo(() => computeLayout(graph), [graph])
  const components = graph.components ?? []
  const connections = graph.connections ?? []
  const markerId = `${idPrefix}-arrow`
  const byId = new Map(components.map((component) => [component.id, component]))

  if (components.length === 0) {
    return <p className="text-sm text-silver">This view has no components to draw.</p>
  }

  return (
    <svg
      role="img"
      aria-label={`${graph.title}: ${components.length} components and ${connections.length} connections`}
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      width={`${Math.round(layout.width * zoom)}`}
      height={`${Math.round(layout.height * zoom)}`}
      className="block max-w-none"
      data-testid="architecture-svg"
    >
      <defs>
        <marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill={C.textSecondary} />
        </marker>
      </defs>

      {(graph.trust_boundaries ?? []).map((boundary) => {
        const members = (boundary.component_ids ?? []).map((id) => layout.positions[id]).filter((p): p is Point => Boolean(p))
        if (members.length === 0) return null
        const minX = Math.min(...members.map((p) => p.x)) - 18
        const minY = Math.min(...members.map((p) => p.y)) - 34
        const maxX = Math.max(...members.map((p) => p.x)) + NODE_WIDTH + 18
        const maxY = Math.max(...members.map((p) => p.y)) + NODE_HEIGHT + 18
        return (
          <g key={boundary.id} data-testid="trust-boundary">
            <rect
              x={minX}
              y={minY}
              width={maxX - minX}
              height={maxY - minY}
              rx={18}
              fill="none"
              stroke={C.trustBoundary}
              strokeOpacity={0.5}
              strokeDasharray="6 6"
              strokeWidth={1.5}
            />
            <text x={minX + 14} y={minY + 20} fill={C.trustBoundary} fontSize={12} fontFamily="JetBrains Mono, monospace" letterSpacing="0.08em">
              {clip(boundary.label.toUpperCase(), 44)}
            </text>
          </g>
        )
      })}

      {connections.map((connection) => {
        const from = layout.positions[connection.source]
        const to = layout.positions[connection.target]
        if (!from || !to) return null
        const style = connectionStyle(connection)
        const { d, mid } = edgePath(from, to)
        const label = connection.label ? clip(connection.label, 30) : null
        return (
          <g key={connection.id} data-testid="connection">
            <path
              d={d}
              fill="none"
              stroke={style.stroke}
              strokeOpacity={style.opacity}
              strokeWidth={1.75}
              strokeDasharray={style.dash}
              markerEnd={`url(#${markerId})`}
            >
              <title>{connection.label ?? `${connection.source} → ${connection.target}`}</title>
            </path>
            {label ? (
              <g transform={`translate(${mid.x} ${mid.y})`}>
                <rect x={-(label.length * 3.3 + 8)} y={-10} width={label.length * 6.6 + 16} height={18} rx={9} fill={C.labelBackground} fillOpacity={0.9} stroke={C.nodeBorder} />
                <text textAnchor="middle" y={3} fontSize={11} fill={C.text} fillOpacity={0.9} fontFamily="Inter, system-ui, sans-serif">
                  {label}
                </text>
              </g>
            ) : null}
          </g>
        )
      })}

      {components.map((component) => {
        const position = layout.positions[component.id]
        const source = byId.get(component.id)
        if (!position || !source) return null
        const selected = selectedId === component.id
        const service = serviceFor(component, provider)
        const accent = TIER_ACCENT[component.tier] ?? C.textMuted
        const deployment = component.deployment_target ? DEPLOYMENT_LABEL[component.deployment_target] ?? humanise(component.deployment_target) : 'Not stated'
        const deploymentColour = component.deployment_target === 'serverless_function' ? C.nodeSelected : component.deployment_target === 'managed_service' ? C.connection : C.textSecondary
        return (
          <g
            key={component.id}
            role="button"
            tabIndex={0}
            aria-pressed={selected}
            aria-label={`${component.label}. ${TIER_LABELS[component.tier] ?? component.tier}. ${deployment}.`}
            data-testid="diagram-node"
            data-node-id={component.id}
            transform={`translate(${position.x} ${position.y})`}
            onClick={() => onSelect(component.id)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onSelect(component.id)
              }
            }}
            className="cursor-pointer outline-none focus-visible:[&>rect.nyx-node-body]:stroke-primary"
          >
            <title>{`${component.label} — ${deployment}${service ? ` — ${service}` : ''}`}</title>
            <rect
              className="nyx-node-body"
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              rx={14}
              fill={C.node}
              fillOpacity={0.88}
              stroke={selected ? C.nodeSelected : C.nodeBorder}
              strokeWidth={selected ? 2 : 1}
            />
            <rect x={0} y={14} width={4} height={NODE_HEIGHT - 28} rx={2} fill={accent} />
            <text x={18} y={28} fontSize={10.5} fill={C.textSecondary} fontFamily="JetBrains Mono, monospace" letterSpacing="0.1em">
              {clip((TIER_LABELS[component.tier] ?? component.tier).toUpperCase(), 30)}
            </text>
            <text x={18} y={50} fontSize={15} fontWeight={600} fill={C.text} fontFamily="Inter, system-ui, sans-serif">
              {clip(component.label, 26)}
            </text>
            <text x={18} y={68} fontSize={11.5} fill={deploymentColour} fontFamily="Inter, system-ui, sans-serif">
              {clip(deployment, 30)}
            </text>
            <text x={18} y={83} fontSize={11} fill={C.textSecondary} fontFamily="Inter, system-ui, sans-serif">
              {clip(service ? `${service}` : 'No mapping for this provider', 36)}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
