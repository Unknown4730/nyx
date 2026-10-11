/**
 * Visual tone and label mapping for results.
 *
 * Colour is used with intent and never alone: every tone also carries a text
 * label, so a printed report or a colour-blind reader loses nothing.
 *
 * Nothing here decides a verdict. Bands, outcomes and severities come from the
 * API; this module only chooses how an already-decided value looks.
 */
import type { EffortLevel, Severity, SuitabilityOutcome } from '@/types/analysis'

export interface Tone {
  label: string
  text: string
  chip: string
  bar: string
  dot: string
}

const TONE = {
  strong: {
    label: 'Strong',
    text: 'text-acid',
    chip: 'bg-acid/10 text-acid border-acid/35',
    bar: 'bg-acid',
    dot: 'bg-acid',
  },
  good: {
    label: 'Good',
    text: 'text-cyan',
    chip: 'bg-cyan/10 text-cyan border-cyan/35',
    bar: 'bg-cyan',
    dot: 'bg-cyan',
  },
  partial: {
    label: 'Partial',
    text: 'text-violet',
    chip: 'bg-violet/10 text-violet border-violet/35',
    bar: 'bg-violet',
    dot: 'bg-violet',
  },
  caution: {
    label: 'Caution',
    text: 'text-signal',
    chip: 'bg-signal/10 text-signal border-signal/40',
    bar: 'bg-signal',
    dot: 'bg-signal',
  },
  unknown: {
    label: 'Not stated',
    text: 'text-silver',
    chip: 'bg-chalk/[0.04] text-silver border-chalk/[0.12]',
    bar: 'bg-silver/60',
    dot: 'bg-silver/60',
  },
  info: {
    label: 'Info',
    text: 'text-cyan',
    chip: 'bg-cyan/10 text-cyan border-cyan/30',
    bar: 'bg-cyan',
    dot: 'bg-cyan',
  },
} satisfies Record<string, Tone>

export const OUTCOME_TONE: Record<SuitabilityOutcome, Tone> = {
  strong_candidate: TONE.strong,
  suitable_with_modifications: TONE.good,
  partial_serverless_adoption: TONE.partial,
  further_assessment_required: TONE.unknown,
  poor_candidate_for_proposed_serverless: TONE.caution,
}

export const SEVERITY_TONE: Record<Severity, Tone> = {
  critical: TONE.caution,
  high: TONE.caution,
  medium: TONE.partial,
  low: TONE.good,
  info: TONE.info,
}

export const EFFORT_TONE: Record<EffortLevel, Tone> = {
  low: TONE.good,
  moderate: TONE.partial,
  high: TONE.caution,
  further_assessment_required: TONE.unknown,
}

/** `ServiceMapping.confidence` is a free string in the schema; unknown values fall back to neutral. */
export const CONFIDENCE_TONE: Record<string, Tone> = {
  high: TONE.strong,
  medium: TONE.partial,
  low: TONE.unknown,
}

export function outcomeTone(outcome: SuitabilityOutcome | null | undefined): Tone {
  return (outcome && OUTCOME_TONE[outcome]) || TONE.unknown
}

export function severityTone(severity: Severity | null | undefined): Tone {
  return (severity && SEVERITY_TONE[severity]) || TONE.unknown
}

export function effortTone(level: EffortLevel | null | undefined): Tone {
  return (level && EFFORT_TONE[level]) || TONE.unknown
}

export function confidenceTone(level: string | null | undefined): Tone {
  return (level && CONFIDENCE_TONE[level]) || TONE.unknown
}

export const TONES = TONE

export const PROVIDER_ACCENT: Record<string, { label: string; short: string; dot: string }> = {
  aws: { label: 'AWS', short: 'AWS', dot: 'bg-[#FF9F43]' },
  gcp: { label: 'Google Cloud', short: 'GCP', dot: 'bg-cyan' },
  azure: { label: 'Azure', short: 'Azure', dot: 'bg-violet' },
}

/** Tier labels for the architecture layout bands. */
export const TIER_LABELS: Record<string, string> = {
  presentation: 'Presentation',
  edge: 'Edge & delivery',
  application: 'Application logic',
  integration: 'Integration & async',
  processing: 'Processing',
  data: 'State & data',
  security: 'Security & identity',
  operations: 'Operations',
}

/** Accent stripe per tier, so the diagram groups components without extra colours. */
export const TIER_ACCENT: Record<string, string> = {
  presentation: '#70E7FF',
  edge: '#70E7FF',
  application: '#D7FF3F',
  integration: '#A78BFA',
  processing: '#FF9F43',
  data: '#A78BFA',
  security: '#FF5B6E',
  operations: '#9296A3',
}

export const DEPLOYMENT_LABEL: Record<string, string> = {
  serverless_function: 'Serverless function',
  managed_service: 'Managed service',
  container: 'Container',
  virtual_machine: 'Virtual machine',
  retain_as_is: 'Retain as is',
  review_required: 'Needs review',
}

export const CONVENTIONAL_LABEL = 'Current (serverful)'
export const PROPOSED_LABEL = 'Proposed (serverless-first)'
