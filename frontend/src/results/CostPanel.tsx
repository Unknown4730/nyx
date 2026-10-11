import { Meter, Panel, SectionHeading, Stat, TD, TH, Table } from '@/components/ui'
import { decimal, percent } from '@/lib/format'
import { TONES } from '@/lib/tone'
import type { AnalysisResult } from '@/types/analysis'

export function CostPanel({ result }: { result: AnalysisResult }) {
  const cost = result.cost
  const comparison = cost.comparison
  if (!comparison) {
    return (
      <Panel>
        <p className="text-sm text-silver">The cost model did not return a comparison for this analysis.</p>
      </Panel>
    )
  }
  const ratio = comparison.ratio_proposed_to_conventional
  const largest = Math.max(comparison.conventional_total, comparison.proposed_total, 0.0001)
  const insufficient = (cost.insufficient_inputs ?? []).length > 0

  return (
    <div className="grid gap-6">
      <Panel labelledBy="cost-heading" className="border-violet/25">
        <SectionHeading
          id="cost-heading"
          eyebrow={`Model · ${cost.unit_name}`}
          title="Relative cost comparison"
          description={cost.disclaimer}
        />
        {insufficient ? (
          <div role="note" className="mt-4 rounded-xl border border-violet/35 bg-violet/[0.08] p-3 text-sm">
            <p className="font-semibold text-violet">Not enough stated inputs for a comparison</p>
            <ul className="mt-2 list-disc pl-5 text-chalk/90">
              {(cost.insufficient_inputs ?? []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <dl className="mt-6 grid gap-6 sm:grid-cols-3">
          <Stat label="Conventional" value={decimal(comparison.conventional_total, 2)} hint={cost.unit} />
          <Stat label="Proposed" value={decimal(comparison.proposed_total, 2)} hint={cost.unit} />
          <Stat
            label="Proposed vs conventional"
            value={ratio !== null && ratio !== undefined ? `${decimal(ratio, 2)}×` : 'not stated'}
            hint={`${comparison.model_relative_change_pct >= 0 ? '+' : ''}${decimal(comparison.model_relative_change_pct, 1)}% in the model`}
          />
        </dl>
        <div className="mt-6 space-y-3">
          {[
            { label: 'Conventional', value: comparison.conventional_total, tone: TONES.unknown },
            { label: 'Proposed', value: comparison.proposed_total, tone: TONES.good },
          ].map((row) => (
            <div key={row.label} className="grid grid-cols-[6rem_minmax(0,1fr)_4rem] items-center gap-3 text-sm">
              <span className="text-silver">{row.label}</span>
              <Meter value={row.value} max={largest} tone={row.tone} label={`${row.label} total ${decimal(row.value, 2)} ${cost.unit}`} />
              <span className="nyx-metric text-right">{decimal(row.value, 2)}</span>
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs text-silver">{cost.period}. Units: {cost.unit} (the relative monthly cost of one small always-on compute unit). No currency is implied.</p>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        {(cost.scenarios ?? []).map((scenario) => (
          <Panel key={scenario.id}>
            <SectionHeading eyebrow={scenario.id === 'proposed' ? 'Proposed' : 'Current'} title={scenario.label} description={scenario.description} />
            <dl className="mt-5 grid grid-cols-4 gap-3 text-sm">
              <Stat label="Fixed" value={decimal(scenario.fixed_ricu, 2)} />
              <Stat label="Variable" value={decimal(scenario.variable_ricu, 2)} />
              <Stat label="Ops" value={decimal(scenario.operational_ricu, 2)} />
              <Stat label="Total" value={decimal(scenario.total_ricu, 2)} />
            </dl>
            <div className="mt-5">
              <Table caption={`Cost line items for ${scenario.label}`}>
                <thead>
                  <tr>
                    <th className={TH}>Item</th>
                    <th className={TH}>Qty</th>
                    <th className={TH}>Units</th>
                    <th className={TH}>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {(scenario.line_items ?? []).map((item) => (
                    <tr key={item.id}>
                      <td className={`${TD} text-xs`}>
                        {item.label}
                        <p className="mt-0.5 text-2xs text-silver">{item.basis}</p>
                      </td>
                      <td className={`${TD} nyx-metric`}>{decimal(item.quantity, 2)}</td>
                      <td className={`${TD} text-xs text-silver`}>{item.unit}</td>
                      <td className={`${TD} nyx-metric`}>{decimal(item.ricu, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
            {(scenario.assumptions ?? []).length ? (
              <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-silver">
                {(scenario.assumptions ?? []).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}
          </Panel>
        ))}
      </div>

      <Panel>
        <SectionHeading eyebrow="Sensitivity" title="How the comparison moves with traffic" description="Each driver is changed on its own; deltas are relative to the base case." />
        <div className="mt-5">
          <Table caption="Sensitivity of the cost comparison">
            <thead>
              <tr>
                <th className={TH}>Driver</th>
                <th className={TH}>Scenario</th>
                <th className={TH}>Conventional</th>
                <th className={TH}>Proposed</th>
              </tr>
            </thead>
            <tbody>
              {(cost.sensitivity ?? []).map((entry) => (
                <tr key={entry.name}>
                  <td className={`${TD} text-sm`}>{entry.name}</td>
                  <td className={`${TD} text-xs text-silver`}>{entry.low_label}</td>
                  <td className={`${TD} nyx-metric`}>{percent(entry.conventional_delta_pct / 100, 1)}</td>
                  <td className={`${TD} nyx-metric`}>{percent(entry.proposed_delta_pct / 100, 1)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
        {(cost.sensitivity ?? []).map((entry) => (
          <p key={`${entry.name}-note`} className="mt-3 text-xs text-silver">
            {entry.name}: {entry.note}
          </p>
        ))}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel>
          <SectionHeading eyebrow="Method" title="How the model works" />
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-chalk/90">
            {(cost.methodology ?? []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </Panel>
        <Panel>
          <SectionHeading eyebrow="Limits" title="What the model cannot tell you" />
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-chalk/90">
            {(cost.limitations ?? []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          {(cost.assumptions ?? []).length ? (
            <>
              <p className="nyx-eyebrow mt-5">Assumptions</p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-silver">
                {(cost.assumptions ?? []).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          ) : null}
        </Panel>
      </div>

      <Panel>
        <SectionHeading eyebrow="Rates" title="Rate table used by the model" description="Relative units only. These are model parameters, not provider prices." />
        <div className="mt-5">
          <Table caption="Rate table">
            <thead>
              <tr>
                <th className={TH}>Quantity</th>
                <th className={TH}>Unit</th>
                <th className={TH}>RICU</th>
                <th className={TH}>Note</th>
              </tr>
            </thead>
            <tbody>
              {(cost.rate_table ?? []).map((rate, index) => (
                <tr key={`${String(rate.quantity ?? '')}-${index}`}>
                  <td className={`${TD} text-sm`}>{String(rate.quantity ?? '')}</td>
                  <td className={`${TD} text-xs text-silver`}>{String(rate.unit ?? '')}</td>
                  <td className={`${TD} nyx-metric`}>{decimal(Number(rate.ricu), 2)}</td>
                  <td className={`${TD} text-xs text-silver`}>{String(rate.note ?? '')}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      </Panel>
    </div>
  )
}
