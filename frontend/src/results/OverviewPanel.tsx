import { Chip, Meter, Panel, ScoreGauge, SectionHeading, TD, TH, Table, ToneChip } from '@/components/ui'
import { decimal, humanise, num, percent, signed } from '@/lib/format'
import { outcomeTone, severityTone, TONES } from '@/lib/tone'
import type { AnalysisResult } from '@/types/analysis'

const PROVENANCE_LABEL: Record<string, string> = {
  user_provided: 'You stated it',
  template: 'Template value',
  inferred: 'Inferred from text',
  default: 'Default used',
  missing: 'Not stated',
  ai: 'AI-proposed',
}

function provenanceLabel(basis: string | undefined): string {
  return (basis && PROVENANCE_LABEL[basis]) || humanise(basis, 'Not stated')
}

export function OverviewPanel({ result }: { result: AnalysisResult }) {
  const suitability = result.suitability
  const tone = outcomeTone(suitability.outcome)
  const provisional = suitability.provisional_score !== null && suitability.provisional_score !== undefined
  const displayScore = provisional ? suitability.provisional_score : suitability.score
  const requirements = result.application
  const provenance = requirements.provenance ?? {}

  const requirementRows: [string, string, string | undefined][] = [
    ['Application type', humanise(requirements.application_type, 'Not stated'), provenance.application_type?.basis],
    ['Expected users', num(requirements.expected_users), provenance.expected_users?.basis],
    ['Traffic pattern', humanise(requirements.traffic_pattern ?? undefined, 'Not stated'), provenance.traffic_pattern?.basis],
    ['Availability', humanise(requirements.availability ?? undefined, 'Not stated'), provenance.availability?.basis],
    ['Budget preference', humanise(requirements.budget ?? undefined, 'Not stated'), provenance.budget?.basis],
    [
      'Data storage',
      requirements.data_storage?.length ? requirements.data_storage.map((item) => humanise(item)).join(', ') : 'Not stated',
      provenance.data_storage?.basis,
    ],
  ]

  return (
    <div className="grid gap-6">
      <Panel labelledBy="verdict-heading">
        <div className="flex flex-col gap-6 md:flex-row md:items-center">
          <ScoreGauge
            score={displayScore}
            provisional={provisional}
            tone={tone}
            caption="out of 100"
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <ToneChip tone={tone}>{humanise(suitability.outcome)}</ToneChip>
              <Chip>{humanise(suitability.recommended_pattern, 'Pattern not stated')}</Chip>
              <Chip>{result.engine_mode === 'ai_assisted' ? 'AI-assisted inputs' : 'Rules engine'}</Chip>
            </div>
            <h2 id="verdict-heading" className="mt-3 text-xl font-semibold tracking-tight text-chalk">
              {suitability.headline}
            </h2>
            <p className="nyx-subtitle mt-2">{suitability.rationale}</p>
            {provisional ? (
              <div role="note" className="mt-4 rounded-xl border border-violet/35 bg-violet/[0.08] p-3 text-sm text-chalk/90">
                <p className="font-semibold text-violet">Provisional verdict</p>
                <p className="mt-1">
                  The score is shown for orientation only. Several deciding inputs are not stated, so NYX has not issued a
                  final outcome. Answer the open questions below to firm it up.
                </p>
              </div>
            ) : null}
          </div>
        </div>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel labelledBy="requirements-heading">
          <SectionHeading id="requirements-heading" eyebrow="Inputs" title="What the analysis was given" description="Each value is labelled by where it came from. Anything marked “Not stated” was not assumed." />
          <dl className="mt-5 divide-y divide-chalk/[0.06]">
            {requirementRows.map(([label, value, basis]) => (
              <div key={label} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_auto] items-baseline gap-3 py-2.5">
                <dt className="text-sm text-silver">{label}</dt>
                <dd className="truncate text-sm text-chalk">{value}</dd>
                <dd className="text-2xs text-silver">{provenanceLabel(basis)}</dd>
              </div>
            ))}
          </dl>
        </Panel>

        <Panel labelledBy="workload-heading">
          <SectionHeading id="workload-heading" eyebrow="Workload" title={humanise(result.workload.classification, 'Workload')} description={result.workload.headline} />
          <ul className="mt-5 space-y-2 text-sm text-chalk/90">
            {[result.workload.request_shape, result.workload.data_shape, result.workload.execution_shape].filter(Boolean).map((line) => (
              <li key={line} className="nyx-inset p-3">
                {line}
              </li>
            ))}
          </ul>
          {(result.workload.signals ?? []).length > 0 ? (
            <div className="mt-4">
              <p className="nyx-eyebrow">Signals read from the description</p>
              <ul className="mt-2 flex flex-wrap gap-2">
                {(result.workload.signals ?? []).map((signal) => (
                  <li key={signal}>
                    <Chip>{signal}</Chip>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Panel>
      </div>

      <Panel labelledBy="factors-heading">
        <SectionHeading
          id="factors-heading"
          eyebrow="Method"
          title="How the score was built"
          description={`Weighted factors, each shown with its weight, its effect and the evidence behind it. Positive impact raises the score; negative lowers it. Formula: ${suitability.methodology.formula}`}
        />
        <div className="mt-5">
          <Table caption="Scoring factors, weights and evidence">
            <thead>
              <tr>
                <th className={TH}>Factor</th>
                <th className={TH}>Weight</th>
                <th className={TH}>Impact</th>
                <th className={TH}>Effect</th>
                <th className={TH}>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {(suitability.factors ?? []).map((factor) => (
                <tr key={factor.id}>
                  <td className={`${TD} min-w-[11rem]`}>
                    <p className="font-medium">{factor.name}</p>
                    <p className="mt-0.5 text-2xs text-silver">{provenanceLabel(factor.basis)}</p>
                  </td>
                  <td className={`${TD} nyx-metric`}>{percent(factor.weight)}</td>
                  <td className={`${TD} nyx-metric`}>{signed(factor.impact)}</td>
                  <td className={`${TD} w-44`}>
                    <Meter
                      value={factor.impact + 1}
                      max={2}
                      tone={factor.impact < -0.15 ? TONES.caution : factor.impact > 0.15 ? TONES.good : TONES.unknown}
                      label={`${factor.name} impact ${signed(factor.impact)}`}
                    />
                    <p className="mt-1 text-2xs text-silver">{humanise(factor.direction)}</p>
                  </td>
                  <td className={`${TD} text-xs text-silver`}>
                    <p>{factor.explanation}</p>
                    {factor.evidence ? <p className="mt-1 text-chalk/70">{factor.evidence}</p> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
        {suitability.methodology.notes?.length ? (
          <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-silver">
            {suitability.methodology.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel>
          <SectionHeading eyebrow="Evidence" title="Supports the verdict" />
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-chalk/90">
            {(suitability.supporting_evidence ?? []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          {(suitability.supporting_evidence ?? []).length === 0 ? <p className="mt-3 text-sm text-silver">No favourable evidence was stated.</p> : null}
        </Panel>
        <Panel>
          <SectionHeading eyebrow="Risk" title="Concerns" />
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-chalk/90">
            {(suitability.concerns ?? []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          {(suitability.concerns ?? []).length === 0 ? <p className="mt-3 text-sm text-silver">No concerns were raised by the rules.</p> : null}
        </Panel>
        <Panel>
          <SectionHeading eyebrow="Gaps" title="Missing inputs" description="Missing inputs are never counted as favourable." />
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-chalk/90">
            {(suitability.missing_inputs ?? []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          {(suitability.missing_inputs ?? []).length === 0 ? <p className="mt-3 text-sm text-silver">Every scored input was stated or inferred.</p> : null}
        </Panel>
      </div>

      {(suitability.components ?? []).length > 0 ? (
        <Panel labelledBy="components-heading">
          <SectionHeading
            id="components-heading"
            eyebrow="Per component"
            title="Component-level suitability"
            description="Each serverless candidate is scored separately, so a single unsuitable part does not condemn the whole system."
          />
          <div className="mt-5">
            <Table caption="Suitability by component">
              <thead>
                <tr>
                  <th className={TH}>Component</th>
                  <th className={TH}>Score</th>
                  <th className={TH}>Outcome</th>
                  <th className={TH}>Recommendation</th>
                  <th className={TH}>Reason</th>
                </tr>
              </thead>
              <tbody>
                {(suitability.components ?? []).map((component) => (
                  <tr key={component.component_id}>
                    <td className={`${TD} font-medium`}>{component.component_label}</td>
                    <td className={`${TD} nyx-metric`}>{decimal(component.score, 0)}</td>
                    <td className={TD}>
                      <ToneChip tone={outcomeTone(component.outcome)}>{humanise(component.outcome)}</ToneChip>
                    </td>
                    <td className={`${TD} text-sm`}>{humanise(component.recommendation)}</td>
                    <td className={`${TD} text-xs text-silver`}>{component.recommendation_reason}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        </Panel>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel>
          <SectionHeading eyebrow="Decisions" title="Open questions" description="Answering these would firm up the verdict." />
          {(result.open_questions ?? []).length === 0 ? (
            <p className="mt-4 text-sm text-silver">No open questions were raised.</p>
          ) : (
            <ol className="mt-4 space-y-3">
              {(result.open_questions ?? []).map((question) => (
                <li key={question.id} className="nyx-inset p-3">
                  <p className="text-sm font-medium text-chalk">{question.question}</p>
                  <p className="mt-1 text-xs text-silver">{question.why_it_matters}</p>
                </li>
              ))}
            </ol>
          )}
        </Panel>
        <Panel>
          <SectionHeading eyebrow="Transparency" title="Assumptions" description="Values NYX used because nothing stronger was stated." />
          {(result.assumptions ?? []).length === 0 ? (
            <p className="mt-4 text-sm text-silver">No assumptions were needed.</p>
          ) : (
            <ul className="mt-4 space-y-2">
              {(result.assumptions ?? []).map((assumption) => (
                <li key={assumption.id} className="nyx-inset p-3 text-sm">
                  <p className="text-chalk/90">{assumption.statement}</p>
                  <p className="mt-1 text-2xs text-silver">
                    {humanise(assumption.basis)} · {assumption.impact}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Panel labelledBy="limitations-heading">
        <SectionHeading id="limitations-heading" eyebrow="Read before deciding" title="Limitations of this analysis" />
        <ul className="mt-4 space-y-2">
          {(result.limitations ?? []).map((limitation) => (
            <li key={limitation.code} className="flex gap-3 text-sm text-chalk/90">
              <span className="mt-0.5">
                <ToneChip tone={severityTone(limitation.severity === 'warning' ? 'medium' : 'info')}>
                  {limitation.severity === 'warning' ? 'Warning' : 'Info'}
                </ToneChip>
              </span>
              <span>{limitation.statement}</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs text-silver">
          Engine {result.rule_pack_version} · catalogue {result.catalog_version} · analysed in {num(result.duration_ms)} ms
          {result.ai.note ? ` · ${result.ai.note}` : ''}
        </p>
      </Panel>
    </div>
  )
}
