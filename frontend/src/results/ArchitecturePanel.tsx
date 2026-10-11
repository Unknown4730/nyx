import { useState } from 'react'

import { ArchitectureDiagram } from '@/components/ArchitectureDiagram'
import { Chip, Disclosure, Panel, SectionHeading, TD, TH, Table } from '@/components/ui'
import { useNyx } from '@/state/NyxProvider'
import { CONVENTIONAL_LABEL, DEPLOYMENT_LABEL, PROPOSED_LABEL, PROVIDER_ACCENT, TIER_LABELS } from '@/lib/tone'
import { humanise } from '@/lib/format'
import type { AnalysisResult, CloudProvider, Component } from '@/types/analysis'

const PROVIDERS: CloudProvider[] = ['aws', 'gcp', 'azure']
const ZOOM_STEPS = [0.6, 0.8, 1, 1.25]

function label(view: string): string {
  if (view === 'conventional') return CONVENTIONAL_LABEL
  if (view === 'proposed') return PROPOSED_LABEL
  return humanise(view)
}

function TraitList({ component }: { component: Component }) {
  const traits = component.traits ?? {}
  const flags: [string, boolean | undefined][] = [
    ['Stateful', traits.stateful],
    ['Always on', traits.always_on],
    ['Event triggered', traits.event_triggered],
    ['Persistent connections', traits.persistent_connections],
    ['CPU / memory heavy', traits.cpu_or_memory_intensive],
    ['GPU required', traits.gpu_required],
    ['Custom runtime', traits.custom_runtime],
  ]
  const active = flags.filter(([, value]) => value)
  return (
    <div className="flex flex-wrap gap-2">
      {active.length === 0 ? <Chip>No stateful or heavy traits recorded</Chip> : null}
      {active.map(([name]) => (
        <Chip key={name}>{name}</Chip>
      ))}
    </div>
  )
}

function Inspector({ component, provider, view }: { component: Component | null; provider: CloudProvider; view: string }) {
  if (!component) {
    return (
      <div className="nyx-inset p-5 text-sm text-silver">
        <p className="font-medium text-chalk">Select a component</p>
        <p className="mt-2">
          Choose any box in the diagram, or press Tab to move between components and Enter to select one. Its details, the
          cloud service for {PROVIDER_ACCENT[provider]?.label ?? provider}, and any caveats appear here.
        </p>
      </div>
    )
  }
  const mapping = component.mappings?.[provider]
  return (
    <article aria-live="polite" className="nyx-inset space-y-4 p-5 text-sm" data-testid="inspector">
      <header>
        <p className="nyx-eyebrow">{TIER_LABELS[component.tier] ?? component.tier}</p>
        <h3 className="mt-1 text-lg font-semibold text-chalk">{component.label}</h3>
        <p className="mt-1 text-xs text-silver">
          {label(view)} · {component.deployment_target ? (DEPLOYMENT_LABEL[component.deployment_target] ?? humanise(component.deployment_target)) : 'Deployment not stated'}
        </p>
      </header>
      {component.description ? <p className="text-chalk/90">{component.description}</p> : null}
      <section aria-label="Cloud service">
        <p className="nyx-eyebrow">{PROVIDER_ACCENT[provider]?.label ?? provider} service</p>
        {mapping ? (
          <div className="mt-2 space-y-2">
            <p className="font-medium text-chalk">
              {mapping.service_url ? (
                <a href={mapping.service_url} target="_blank" rel="noopener noreferrer" className="nyx-link">
                  {mapping.service_name}
                </a>
              ) : (
                mapping.service_name
              )}
            </p>
            <p className="text-xs text-silver">
              {humanise(mapping.serverless_class, 'Class not stated')} · confidence {humanise(mapping.confidence, 'not stated')}
            </p>
            {mapping.reason ? <p className="text-xs text-chalk/80">{mapping.reason}</p> : null}
            {mapping.differences?.length ? (
              <ul className="list-disc space-y-1 pl-5 text-xs text-silver">
                {mapping.differences.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : (
          <p className="mt-2 text-silver">No mapping exists for this component on {PROVIDER_ACCENT[provider]?.label ?? provider}.</p>
        )}
      </section>
      <section aria-label="Execution traits">
        <p className="nyx-eyebrow">Execution traits</p>
        <div className="mt-2">
          <TraitList component={component} />
        </div>
      </section>
      {component.warnings?.length ? (
        <section aria-label="Warnings">
          <p className="nyx-eyebrow text-signal">Warnings</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-chalk/85">
            {component.warnings.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {component.assumptions?.length ? (
        <section aria-label="Assumptions">
          <p className="nyx-eyebrow">Assumptions</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-silver">
            {component.assumptions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  )
}

export function ArchitecturePanel({ result }: { result: AnalysisResult }) {
  const { graph, view, setView, provider, setProvider, selectedId, select, selectedComponent } = useNyx()
  const [zoomIndex, setZoomIndex] = useState(2)
  const zoom = ZOOM_STEPS[zoomIndex] ?? 1

  if (!graph) {
    return (
      <Panel>
        <p className="text-sm text-silver">This analysis has no architecture views.</p>
      </Panel>
    )
  }

  const views = (result.architectures ?? []).map((item) => item.id)
  const components = graph.components ?? []
  const connections = graph.connections ?? []
  const nameOf = new Map(components.map((component) => [component.id, component.label]))

  return (
    <div className="grid gap-6">
      <Panel labelledBy="architecture-heading">
        <SectionHeading
          id="architecture-heading"
          eyebrow="Blueprint"
          title={graph.title}
          description={graph.summary}
          action={
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Diagram options">
              <div className="flex rounded-xl border border-chalk/10 bg-obsidian/60 p-1" role="tablist" aria-label="Architecture view">
                {views.map((id) => (
                  <button
                    key={id}
                    role="tab"
                    type="button"
                    aria-selected={view === id}
                    className="nyx-tab"
                    onClick={() => setView(id)}
                  >
                    {label(id)}
                  </button>
                ))}
              </div>
              <label className="sr-only" htmlFor="provider-select">
                Cloud provider
              </label>
              <select
                id="provider-select"
                className="nyx-field w-auto py-1.5 text-sm"
                value={provider}
                onChange={(event) => setProvider(event.target.value as CloudProvider)}
              >
                {PROVIDERS.map((item) => (
                  <option key={item} value={item}>
                    {PROVIDER_ACCENT[item]?.label ?? item}
                  </option>
                ))}
              </select>
              <div className="flex items-center gap-1" role="group" aria-label="Zoom">
                <button type="button" className="nyx-btn-secondary px-3 py-1.5" onClick={() => setZoomIndex((i) => Math.max(0, i - 1))} disabled={zoomIndex === 0} aria-label="Zoom out">
                  −
                </button>
                <span className="w-14 text-center font-mono text-xs text-silver" aria-live="polite">
                  {Math.round(zoom * 100)}%
                </span>
                <button
                  type="button"
                  className="nyx-btn-secondary px-3 py-1.5"
                  onClick={() => setZoomIndex((i) => Math.min(ZOOM_STEPS.length - 1, i + 1))}
                  disabled={zoomIndex === ZOOM_STEPS.length - 1}
                  aria-label="Zoom in"
                >
                  +
                </button>
              </div>
            </div>
          }
        />
        <p className="mt-3 text-xs text-silver">
          Components are placed by tier and boxed trust boundaries show where data crosses from less to more trusted zones. Switching
          provider relabels the same logical components; nothing is deployed.
        </p>
      </Panel>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Panel className="p-3 sm:p-3" raised>
          <div
            className="nyx-scroll-x max-h-[70vh] rounded-xl bg-obsidian/70 p-4"
            role="region"
            aria-label={`${graph.title} diagram. Scroll horizontally to see all components.`}
            tabIndex={0}
          >
            <ArchitectureDiagram
              graph={graph}
              provider={provider}
              selectedId={selectedId}
              onSelect={select}
              zoom={zoom}
              idPrefix={`diagram-${graph.id}`}
            />
          </div>
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-2 px-1 text-2xs text-silver" aria-label="Legend">
            <li>Dashed violet: asynchronous delivery</li>
            <li>Dotted grey: optional path</li>
            <li>Red: crosses a trust boundary</li>
          </ul>
        </Panel>
        <div className="xl:sticky xl:top-6 xl:self-start">
          <Panel>
            <p className="nyx-eyebrow">Inspector</p>
            <div className="mt-3">
              <Inspector component={selectedComponent} provider={provider} view={graph.id} />
            </div>
          </Panel>
        </div>
      </div>

      {graph.caveats?.length ? (
        <Panel>
          <SectionHeading eyebrow="Caveats" title="What this blueprint does not show" />
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-chalk/90">
            {graph.caveats.map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <Disclosure summary="Text alternative: every component and connection in this view">
        <div className="grid gap-6">
          <Table caption="Components in this view">
            <thead>
              <tr>
                <th className={TH}>Component</th>
                <th className={TH}>Tier</th>
                <th className={TH}>Deployment</th>
                <th className={TH}>{PROVIDER_ACCENT[provider]?.label ?? provider} service</th>
              </tr>
            </thead>
            <tbody>
              {components.map((component) => (
                <tr key={component.id}>
                  <td className={TD}>{component.label}</td>
                  <td className={TD}>{TIER_LABELS[component.tier] ?? humanise(component.tier)}</td>
                  <td className={TD}>{component.deployment_target ? (DEPLOYMENT_LABEL[component.deployment_target] ?? humanise(component.deployment_target)) : 'Not stated'}</td>
                  <td className={TD}>{component.mappings?.[provider]?.service_name ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </Table>
          <Table caption="Connections in this view">
            <thead>
              <tr>
                <th className={TH}>From</th>
                <th className={TH}>To</th>
                <th className={TH}>Kind</th>
                <th className={TH}>Notes</th>
              </tr>
            </thead>
            <tbody>
              {connections.map((connection) => (
                <tr key={connection.id}>
                  <td className={TD}>{nameOf.get(connection.source) ?? connection.source}</td>
                  <td className={TD}>{nameOf.get(connection.target) ?? connection.target}</td>
                  <td className={TD}>{humanise(connection.kind, 'Link')}</td>
                  <td className={`${TD} text-xs text-silver`}>
                    {[connection.label, connection.async_delivery ? 'asynchronous' : null, connection.crosses_trust_boundary ? 'crosses a trust boundary' : null, connection.optional ? 'optional' : null]
                      .filter(Boolean)
                      .join(' · ') || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      </Disclosure>
    </div>
  )
}
