import { Chip, Disclosure, Panel, SectionHeading, TD, TH, Table, ToneChip } from '@/components/ui'
import { decimal, humanise } from '@/lib/format'
import { effortTone } from '@/lib/tone'
import type { AnalysisResult } from '@/types/analysis'

function ListBlock({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="mt-3 text-sm text-silver">{empty}</p>
  return (
    <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-chalk/90">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  )
}

export function MigrationPanel({ result }: { result: AnalysisResult }) {
  const migration = result.migration
  return (
    <div className="grid gap-6">
      <Panel labelledBy="migration-heading">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <SectionHeading
            id="migration-heading"
            eyebrow="Roadmap"
            title="Migration plan"
            description={migration.sequencing_rationale}
          />
          <div className="flex flex-wrap items-center gap-2">
            <ToneChip tone={effortTone(migration.overall_complexity)}>{`Complexity: ${humanise(migration.overall_complexity)}`}</ToneChip>
            <Chip>{`Score ${decimal(migration.complexity_score, 1)} / 100`}</Chip>
          </div>
        </div>
      </Panel>

      <Panel labelledBy="phases-heading">
        <SectionHeading id="phases-heading" eyebrow="Sequence" title="Phases" description="Each phase has exit criteria, so progress can be checked rather than assumed." />
        <ol className="mt-6 space-y-4">
          {(migration.phases ?? []).map((phase) => (
            <li key={phase.id} className="nyx-inset relative p-5">
              <div className="flex flex-wrap items-center gap-3">
                <span className="nyx-metric flex h-8 w-8 items-center justify-center rounded-full border border-primary/40 text-sm text-primary">
                  {phase.index}
                </span>
                <h3 className="text-base font-semibold text-chalk">{phase.title}</h3>
                <ToneChip tone={effortTone(phase.effort)}>{`Effort: ${humanise(phase.effort)}`}</ToneChip>
                <Chip>{`Risk: ${humanise(phase.risk)}`}</Chip>
              </div>
              <p className="mt-3 text-sm text-chalk/90">{phase.objective}</p>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <div>
                  <p className="nyx-eyebrow">Activities</p>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-chalk/85">
                    {(phase.activities ?? []).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <p className="nyx-eyebrow">Exit criteria</p>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-chalk/85">
                    {(phase.exit_criteria ?? []).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              </div>
              {(phase.components_touched ?? []).length ? (
                <p className="mt-3 text-2xs text-silver">Touches: {(phase.components_touched ?? []).join(', ')}</p>
              ) : null}
            </li>
          ))}
        </ol>
      </Panel>

      <Panel labelledBy="components-change-heading">
        <SectionHeading id="components-change-heading" eyebrow="Per component" title="What changes, component by component" />
        <div className="mt-5">
          <Table caption="Migration change per component">
            <thead>
              <tr>
                <th className={TH}>Component</th>
                <th className={TH}>Change</th>
                <th className={TH}>Complexity</th>
                <th className={TH}>Reason</th>
              </tr>
            </thead>
            <tbody>
              {(migration.components_requiring_modification ?? []).map((change) => (
                <tr key={change.component_id}>
                  <td className={`${TD} font-medium`}>{change.component_label}</td>
                  <td className={`${TD} text-sm`}>{change.change}</td>
                  <td className={TD}>
                    <ToneChip tone={effortTone(change.complexity)}>{humanise(change.complexity)}</ToneChip>
                  </td>
                  <td className={`${TD} text-xs text-silver`}>{change.reason}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel>
          <SectionHeading eyebrow="Risks" title="Risks to manage" />
          <ListBlock items={(migration.risks ?? [])} empty="No migration risks were raised." />
        </Panel>
        <Panel>
          <SectionHeading eyebrow="Compatibility" title="Compatibility issues" />
          <ListBlock items={(migration.compatibility_issues ?? [])} empty="No compatibility issues were identified by the rules. Confirm against the real code base." />
        </Panel>
        <Panel>
          <SectionHeading eyebrow="Drivers" title="What makes this migration hard" />
          <ListBlock items={(migration.complexity_drivers ?? [])} empty="No complexity drivers were recorded." />
        </Panel>
        <Panel>
          <SectionHeading eyebrow="Validation" title="How to prove each step worked" />
          <ListBlock items={(migration.validation_requirements ?? [])} empty="No validation requirements were recorded." />
        </Panel>
        <Panel>
          <SectionHeading eyebrow="Dependencies" title="Dependencies to review" />
          <ListBlock items={(migration.dependencies_to_review ?? [])} empty="No dependencies were listed." />
        </Panel>
        <Panel>
          <SectionHeading eyebrow="Caveats" title="Assumptions and caveats" />
          <ListBlock items={[...(migration.assumptions ?? []), ...(migration.caveats ?? [])]} empty="No caveats were recorded." />
        </Panel>
      </div>

      <Disclosure summary="Why these phases, in this order">
        <p>{migration.sequencing_rationale}</p>
      </Disclosure>
    </div>
  )
}
