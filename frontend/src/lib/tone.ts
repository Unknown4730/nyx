/**
 * Tone/label mapping for the results.
 *
 * Colour is used with intent and never alone: every tone also carries a text
 * label, so a printed report or a colour-blind reader loses nothing.
 */
import type { EffortLevel, Severity, SuitabilityOutcome } from '@/types/analysis'

export interface Tone {
  label: string
  text: string
  chip: string
  bar: string
  dot: string
  ring: string
}

const TONE = {
  strong: {
    label: 'Strong',
    text: 'text-signal-strong',
    chip: 'bg-signal-strong/10 text-signal-strong border-signal-strong/30',
    bar: 'bg-signal-strong',
    dot: 'bg-signal-strong',
    ring: 'ring-signal-strong/40',
  },
  good: {
    label: 'Good',
    text: 'text-signal-good',
    chip: 'bg-signal-good/10 text-signal-good border-signal-good/30',
    bar: 'bg-signal-good',
    dot: 'bg-signal-good',
    ring: 'ring-signal-good/40',
  },
  partial: {
    label: 'Partial',
    text: 'text-signal-partial',
    chip: 'bg-signal-partial/10 text-signal-partial border-signal-partial/30',
    bar: 'bg-signal-partial',
    dot: 'bg-signal-partial',
    ring: 'ring-signal-partial/40',
  },
  poor: {
    label: 'Caution',
    text: 'text-signal-poor',
    chip: 'bg-signal-poor/10 text-signal-poor border-signal-poor/30',
    bar: 'bg-signal-poor',
    dot: 'bg-signal-poor',
    ring: 'ring-signal-poor/40',
  },
  unknown: {
    label: 'Unknown',
    text: 'text-muted',
    chip: 'bg-white/[0.04] text-muted border-white/10',
    bar: 'bg-muted/60',
    dot: 'bg-muted/60',
    ring: 'ring-white/10',
  },
  info: {
    label: 'Info',
    text: 'text-violet-300',
    chip: 'bg-violet-600/10 text-violet-300 border-violet-500/30',
    bar: 'bg-violet-500',
    dot: 'bg-violet-500',
    ring: 'ring-violet-500/40',
  },
} satisfies Record<string, Tone>

export const OUTCOME_TONE: Record<SuitabilityOutcome, Tone> = {
  strong_candidate: TONE.strong,
  suitable_with_modifications: TONE.good,
  partial_serverless_adoption: TONE.partial,
  further_assessment_required: TONE.unknown,
  poor_candidate_for_proposed_serverless: TONE.poor,
}

export const SEVERITY_TONE: Record<Severity, Tone> = {
  critical: TONE.poor,
  high: TONE.poor,
  medium: TONE.partial,
  low: TONE.good,
  info: TONE.info,
}

export const EFFORT_TONE: Record<EffortLevel, Tone> = {
  low: TONE.good,
  moderate: TONE.partial,
  high: TONE.poor,
  further_assessment_required: TONE.unknown,
}

/** `ServiceMapping.confidence` is a free string in the schema; these are the three
 * grades the catalogue emits, and unknown values fall back to the neutral tone. */
export const EQUIVALENCE_TONE: Record<string, Tone> = {
  near: TONE.strong,
  partial: TONE.partial,
  conceptual: TONE.unknown,
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

export function equivalenceTone(level: string | null | undefined): Tone {
  return (level && EQUIVALENCE_TONE[level]) || TONE.info
}

/** Score → tone, using the same bands the backend publishes in `/api/meta`. */
export function scoreTone(score: number | null | undefined): Tone {
  if (typeof score !== 'number' || !Number.isFinite(score)) return TONE.unknown
  if (score >= 78) return TONE.strong
  if (score >= 62) return TONE.good
  if (score >= 45) return TONE.partial
  return TONE.poor
}

export const PROVIDER_ACCENT: Record<string, { label: string; short: string; dot: string }> = {
  aws: { label: 'AWS', short: 'AWS', dot: 'bg-[#f0a35c]' },
  gcp: { label: 'Google Cloud', short: 'GCP', dot: 'bg-cyan-400' },
  azure: { label: 'Azure', short: 'Azure', dot: 'bg-violet-400' },
}

/** Tiers are the visual bands the layout engine places nodes in. */
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

export const TIER_ACCENT: Record<string, string> = {
  presentation: 'border-l-cyan-400/70',
  edge: 'border-l-cyan-300/60',
  application: 'border-l-violet-500/80',
  integration: 'border-l-violet-400/60',
  processing: 'border-l-[#f0a35c]/70',
  data: 'border-l-signal-good/70',
  security: 'border-l-signal-partial/70',
  operations: 'border-l-muted/60',
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
