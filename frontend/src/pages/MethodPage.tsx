import { Panel, SectionHeading, Stat, TD, TH, Table, ToneChip as Chip } from '@/components/ui'
import { decimal, humanise, num, percent } from '@/lib/format'
import { outcomeTone } from '@/lib/tone'
import { useNyx } from '@/state/NyxProvider'
import type { SuitabilityOutcome } from '@/types/analysis'

export function MethodPage() {
  const { meta, metaError } = useNyx()

  if (!meta) {
    return (
      <div className="grid gap-4">
        <p className="nyx-eyebrow">Method</p>
        <h1 className="nyx-title">How NYX decides</h1>
        <Panel>
          <p className="text-sm text-silver">
            {metaError ?? 'The method is read from the API, which has not answered yet. Nothing is shown in its place.'}
          </p>
        </Panel>
      </div>
    )
  }

  const derivation = meta.derivation
  return (
    <div className="grid gap-8">
      <header>
        <p className="nyx-eyebrow">Method</p>
        <h1 className="nyx-title mt-1">How NYX decides</h1>
        <p className="nyx-subtitle mt-2 max-w-2xl">
          The values on this page are read from the running engine (rule pack {meta.product.rule_pack_version}, catalogue{' '}
          {meta.product.catalog_version}, cost model {meta.product.cost_model_version}). Nothing here is hand-copied.
        </p>
      </header>

      <Panel labelledBy="bands-heading">
        <SectionHeading id="bands-heading" eyebrow="Verdicts" title="Score bands" description={meta.suitability.weight_rationale} />
        <div className="mt-5">
          <Table caption="Score bands and verdicts">
            <thead>
              <tr>
                <th className={TH}>From score</th>
                <th className={TH}>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {meta.suitability.bands.map((band) => (
                <tr key={band.outcome}>
                  <td className={`${TD} nyx-metric`}>{decimal(band.min_score, 0)}+</td>
                  <td className={TD}>
                    <Chip tone={outcomeTone(band.outcome as SuitabilityOutcome)}>{humanise(band.outcome)}</Chip>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
        <p className="mt-4 text-sm text-silver">
          A provisional verdict is issued instead when deciding evidence is missing: if the share of workload weight without
          evidence reaches {percent(meta.suitability.missing_weight_limit)}, NYX reports a score for orientation and withholds
          the outcome.
        </p>
      </Panel>

      <div className="grid gap-6 md:grid-cols-3">
        <Panel>
          <Stat label="Active days a month" value={num(derivation.active_days_per_month)} hint="Used to turn monthly requests into a rate" />
        </Panel>
        <Panel>
          <Stat label="Requests per session" value={num(derivation.requests_per_session)} hint="Derived from the application type" />
        </Panel>
        <Panel>
          <Stat label="Cost unit" value={meta.cost.unit} hint={meta.cost.unit_name} />
        </Panel>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel>
          <SectionHeading eyebrow="Cost" title="What the cost model is" />
          <p className="mt-3 text-sm text-chalk/90">{meta.cost.definition}</p>
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-chalk/85">
            {meta.cost.rates.map((rate) => (
              <li key={rate}>{rate}</li>
            ))}
          </ul>
        </Panel>
        <Panel>
          <SectionHeading eyebrow="Catalogue" title="What the cloud service mapping is" />
          <p className="mt-3 text-sm text-chalk/90">{meta.catalog.disclaimer}</p>
          <p className="mt-3 text-xs text-silver">{meta.catalog.note}</p>
          <p className="mt-3 text-xs text-silver">
            Services per provider:{' '}
            {Object.entries(meta.catalog.services_per_provider)
              .map(([provider, count]) => `${provider.toUpperCase()} ${count}`)
              .join(' · ')}
          </p>
        </Panel>
      </div>

      <Panel>
        <SectionHeading eyebrow="Limits" title="Input limits enforced by the API" />
        <dl className="mt-4 grid gap-4 sm:grid-cols-3">
          <Stat label="Description" value={`${num(meta.limits.description_max_chars)} chars`} />
          <Stat label="Name" value={`${num(meta.limits.name_max_chars)} chars`} />
          <Stat label="Additional requirements" value={`${num(meta.limits.additional_requirements_max_chars)} chars`} />
        </dl>
      </Panel>

      <Panel>
        <SectionHeading eyebrow="AI assist" title="What AI can and cannot change" description={meta.ai.unavailable_reason ?? 'An OpenAI-compatible endpoint is configured.'} />
        <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-chalk/90">
          <li>AI may only propose values for requirement fields. Each proposal is validated before use.</li>
          <li>Scoring, the cloud mapping, the cost model, the security review and the migration plan are always rule-based.</li>
          <li>With no endpoint configured, NYX runs entirely offline on the rules engine.</li>
        </ul>
      </Panel>
    </div>
  )
}
