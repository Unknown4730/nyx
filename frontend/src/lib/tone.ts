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

// Status semantics (colour always comes with a text label):
//   success / strong   icy blue      important / good   violet
//   warning / partial  champagne     error / caution    coral
//   in progress, info  violet        not stated         muted neutral
const TONE = {
  strong: {
    label: 'Strong',
    text: 'text-blue',
    chip: 'bg-blue/10 text-blue border-blue/35',
    bar: 'bg-blue',
    dot: 'bg-blue',
  },
  good: {
    label: 'Good',
    text: 'text-primary',
    chip: 'bg-primary/10 text-primary border-primary/35',
    bar: 'bg-primary',
    dot: 'bg-primary',
  },
  partial: {
    label: 'Partial',
    text: 'text-champagne',
    chip: 'bg-champagne/10 text-champagne border-champagne/35',
    bar: 'bg-champagne',
    dot: 'bg-champagne',
  },
  caution: {
    label: 'Caution',
    text: 'text-coral',
    chip: 'bg-coral/10 text-coral border-coral/40',
    bar: 'bg-coral',
    dot: 'bg-coral',
  },
  unknown: {
    label: 'Not stated',
    text: 'text-silver',
    chip: 'bg-chalk/[0.04] text-silver border-chalk/[0.12]',
    bar: 'bg-muted',
    dot: 'bg-muted',
  },
  info: {
    label: 'Info',
    text: 'text-primary',
    chip: 'bg-primary/10 text-primary border-primary/30',
    bar: 'bg-primary',
    dot: 'bg-primary',
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
  low: TONE.strong,
  info: TONE.info,
}

export const EFFORT_TONE: Record<EffortLevel, Tone> = {
  low: TONE.strong,
  moderate: TONE.partial,
  high: TONE.caution,
  further_assessment_required: TONE.unknown,
}

/** `ServiceMapping.confidence` is a free string in the schema; unknown values fall back to neutral. */
export const CONFIDENCE_TONE: Record<string, Tone> = {
  high: TONE.strong,
  medium: TONE.good,
  low: TONE.partial,
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
  aws: { label: 'AWS', short: 'AWS', dot: 'bg-champagne' },
  gcp: { label: 'Google Cloud', short: 'GCP', dot: 'bg-blue' },
  azure: { label: 'Azure', short: 'Azure', dot: 'bg-primary' },
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

/**
 * Accent stripe per tier. Four categories, each with one job:
 * entry (blue), compute (violet), data and messaging (silver / champagne), security (coral).
 */
export const TIER_ACCENT: Record<string, string> = {
  presentation: '#73D9FF',
  edge: '#73D9FF',
  application: '#B9A0FF',
  processing: '#B9A0FF',
  integration: '#FFC994',
  data: '#A5A9C5',
  security: '#FF8DA1',
  operations: '#777D9C',
}

/** Diagram colours by role, shared by the SVG so the palette lives in one place. */
export const DIAGRAM_COLOUR = {
  node: '#15182B',
  nodeBorder: 'rgba(244,242,255,0.14)',
  nodeSelected: '#B9A0FF',
  text: '#F4F2FF',
  textSecondary: '#A5A9C5',
  textMuted: '#777D9C',
  connection: '#73D9FF',
  asyncConnection: '#B9A0FF',
  optionalConnection: '#A5A9C5', // raised from muted to meet the 3:1 non-text contrast rule
  trustBoundary: '#FF8DA1',
  labelBackground: '#080911',
} as const

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
