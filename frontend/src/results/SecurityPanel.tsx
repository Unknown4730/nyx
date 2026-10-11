import { Chip, Panel, SectionHeading, ToneChip } from '@/components/ui'
import { humanise } from '@/lib/format'
import { severityTone, TONES } from '@/lib/tone'
import type { AnalysisResult, SecurityFinding, VerificationGap } from '@/types/analysis'

const CERTAINTY_LABEL: Record<string, string> = {
  confirmed_in_model: 'Confirmed in the model',
  inferred_risk: 'Inferred risk',
  needs_verification: 'Needs verification',
}

function FindingCard({ finding }: { finding: SecurityFinding }) {
  return (
    <li className="nyx-inset space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <ToneChip tone={severityTone(finding.severity)}>{humanise(finding.severity)}</ToneChip>
        <Chip>{CERTAINTY_LABEL[finding.certainty] ?? humanise(finding.certainty)}</Chip>
        <span className="font-mono text-2xs text-silver">{finding.id}</span>
      </div>
      <p className="font-medium text-chalk">{finding.title}</p>
      <p className="text-sm text-chalk/85">{finding.explanation}</p>
      {(finding.evidence ?? []).length ? (
        <div>
          <p className="nyx-eyebrow">Evidence</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-silver">
            {(finding.evidence ?? []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="text-sm">
        <span className="text-silver">Recommendation: </span>
        <span className="text-chalk">{finding.recommendation}</span>
      </p>
    </li>
  )
}

function GapCard({ gap }: { gap: VerificationGap }) {
  return (
    <li className="nyx-inset space-y-2 p-4">
      <p className="font-medium text-chalk">{gap.question}</p>
      <p className="text-xs text-silver">{gap.why_it_matters}</p>
      <p className="text-sm">
        <span className="text-silver">Suggested check: </span>
        <span className="text-chalk/90">{gap.suggested_check}</span>
      </p>
    </li>
  )
}

export function SecurityPanel({ result }: { result: AnalysisResult }) {
  const security = result.security
  const counts = security.counts ?? {}
  const severities = ['critical', 'high', 'medium', 'low', 'info'] as const
  const totalFindings = severities.reduce((sum, key) => sum + (counts[key] ?? 0), 0)

  return (
    <div className="grid gap-6">
      <Panel labelledBy="security-heading">
        <SectionHeading id="security-heading" eyebrow="Architecture-level review" title="Security findings" description={security.scope_statement} />
        <p className="mt-3 text-xs text-silver">
          Audited view: <span className="text-chalk">{humanise(security.audited_view)}</span>. This is a design review of the modelled
          architecture, not a penetration test or a compliance certification.
        </p>
        <div className="mt-5 flex flex-wrap gap-2" aria-label="Finding counts by severity">
          {severities.map((key) => (
            <span key={key} className="flex items-center gap-2 rounded-chip border border-chalk/10 px-3 py-1 text-xs">
              <ToneChip tone={severityTone(key)}>{humanise(key)}</ToneChip>
              <span className="nyx-metric">{counts[key] ?? 0}</span>
            </span>
          ))}
        </div>
        {totalFindings === 0 ? (
          <p className="mt-4 rounded-xl border border-chalk/[0.08] bg-obsidian/50 p-4 text-sm text-silver">
            No findings were raised by the current rules for the audited view. That is not a statement that the design is secure:
            items in the verification list below are still unanswered.
          </p>
        ) : null}
      </Panel>

      {(security.findings ?? []).length > 0 ? (
        <Panel labelledBy="proposed-findings">
          <SectionHeading id="proposed-findings" eyebrow="Audited view" title="Findings for the audited view" />
          <ul className="mt-4 grid gap-3 lg:grid-cols-2">
            {(security.findings ?? []).map((finding) => (
              <FindingCard key={finding.id} finding={finding} />
            ))}
          </ul>
        </Panel>
      ) : null}

      {(security.baseline_findings ?? []).length > 0 ? (
        <Panel labelledBy="baseline-findings">
          <SectionHeading
            id="baseline-findings"
            eyebrow="Current architecture"
            title="Risks in the current (serverful) baseline"
            description="Shown so the migration can be judged against what exists today. Some of these are resolved, or change shape, in the proposed design."
          />
          <ul className="mt-4 grid gap-3 lg:grid-cols-2">
            {(security.baseline_findings ?? []).map((finding) => (
              <FindingCard key={finding.id} finding={finding} />
            ))}
          </ul>
        </Panel>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel>
          <SectionHeading eyebrow="Still open" title="Verification gaps" description="Questions the model cannot answer from the description alone." />
          {(security.verification_gaps ?? []).length === 0 ? (
            <p className="mt-4 text-sm text-silver">No verification gaps were raised.</p>
          ) : (
            <ul className="mt-4 space-y-3">
              {(security.verification_gaps ?? []).map((gap) => (
                <GapCard key={gap.id} gap={gap} />
              ))}
            </ul>
          )}
        </Panel>
        <Panel>
          <SectionHeading eyebrow="Credit where due" title="What the design gets right" />
          {(security.positives ?? []).length === 0 ? (
            <p className="mt-4 text-sm text-silver">No positive controls were recorded from the description.</p>
          ) : (
            <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-chalk/90">
              {(security.positives ?? []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel>
          <SectionHeading eyebrow="Method" title="How findings are produced" />
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-chalk/90">
            {(security.methodology ?? []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </Panel>
        <Panel>
          <SectionHeading eyebrow="Limits" title="What this review cannot show" />
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-chalk/90">
            {(security.limitations ?? []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p className="mt-4">
            <ToneChip tone={TONES.info}>{`Certainty: ${Object.entries(security.by_certainty ?? {}).map(([key, value]) => `${humanise(key)} ${value}`).join(' · ')}`}</ToneChip>
          </p>
        </Panel>
      </div>
    </div>
  )
}
