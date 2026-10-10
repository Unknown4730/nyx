/**
 * Hand-written types for the descriptive endpoints (`/api/meta`, `/api/ai/status`)
 * and for client-only view models.  The analysis contract itself lives in
 * `./analysis.ts`, which is generated from the backend Pydantic models.
 */
import type {
  AiStatusPayload,
  AnalysisOptions,
  ApplicationRequirements,
  ArchitectureStyle,
  AnalysisResult,
  CloudProvider,
  ProjectSummary,
  SuitabilityOutcome,
} from './analysis'

export type AiStatus = AiStatusPayload

export interface EnumOption {
  value: string
  label: string
  hint?: string | null
}

export interface ProductInfo {
  name: string
  title: string
  tagline: string
  version: string
  schema_version: string
  rule_pack_version: string
  catalog_version: string
  cost_model_version: string
  templates_version: string
}

/** The AI *configuration* view exposed by `/api/meta` (never includes the key). */
export interface AiConfigStatus {
  configured: boolean
  enabled: boolean
  base_url_set: boolean
  api_key_set: boolean
  model: string | null
  timeout_s: number
  max_retries: number
  max_tokens: number
  unavailable_reason: string | null
}

export interface SuitabilityBandInfo {
  outcome: SuitabilityOutcome
  min_score: number
  label: string
}

export interface SuitabilityMeta {
  bands: SuitabilityBandInfo[]
  weight_rationale: string
  factors?: { id: string; name: string; weight: number }[]
}

export interface DerivationMeta {
  active_days_per_month: number
  requests_per_session: number
  sessions_per_user_by_type: Record<string, number>
  peak_ratio_by_traffic: Record<string, number>
}

export interface CostMeta {
  unit: string
  unit_name: string
  definition: string
  rates: string[]
  model_version: string
}

export interface CatalogMeta {
  version: string
  disclaimer: string
  services_per_provider: Record<string, number>
  logical_component_types: number
  equivalence_levels: string[]
  note: string
}

export interface Limits {
  description_max_chars: number
  name_max_chars: number
  additional_requirements_max_chars: number
  max_operations_per_view: { min: number; max: number; default: number }
}

/** The pre-filled starting point a template represents (mirrors `app/services/templates.py`). */
export interface TemplateForm {
  name: string
  description: string
  expected_users?: number | null
  traffic_pattern?: string | null
  application_type?: string
  data_storage?: string[]
  availability?: string | null
  budget?: string | null
  preferred_provider?: string | null
  additional_requirements?: string | null
}

export interface TemplateCard {
  id: string
  name: string
  tagline: string
  icon: string
  summary: string
  highlights: string[]
  expected_outcome_hint: string
  form: TemplateForm
}

export interface MetaPayload {
  product: ProductInfo
  ai: AiConfigStatus
  enums: Record<string, EnumOption[]>
  suitability: SuitabilityMeta
  derivation: DerivationMeta
  cost: CostMeta
  catalog: CatalogMeta
  templates: TemplateCard[]
  limits: Limits
}

export interface ProjectStats {
  total: number
  user_projects: number
  example_projects: number
  newest: string | null
  oldest: string | null
  outcomes: Record<string, number>
  application_types: Record<string, number>
  average_user_score: number | null
  recent: ProjectSummary[]
}

/* ------------------------------------------------------------- client view models */

export type ViewMode = ArchitectureStyle | 'proposed' | 'conventional'

export interface GraphViewModel {
  style: string
  title: string
  summary?: string
  provider: CloudProvider
  caveats: string[]
}

/** One draft row in the New Analysis form (kept separate from the wire model). */
export interface RequirementDraft {
  name: string
  description: string
  expected_users: string
  traffic_pattern: string
  application_type: string
  availability: string
  budget: string
  preferred_provider: string
  data_storage: string[]
  additional_requirements: string
  template_id: string | null
}

export interface DraftEnvelope {
  savedAt: string
  draft: RequirementDraft
  options: { use_ai: boolean; providers: CloudProvider[]; default_provider: CloudProvider | null; max_operations_per_view: number; include_conventional_view: boolean }
  result?: AnalysisResult | null
}

export const EMPTY_DRAFT: RequirementDraft = {
  name: '',
  description: '',
  expected_users: '',
  traffic_pattern: 'unknown',
  application_type: 'unknown',
  availability: 'unknown',
  budget: 'balanced',
  preferred_provider: 'none',
  data_storage: [],
  additional_requirements: '',
  template_id: null,
}

/** Turn a draft into the exact body `POST /api/analyze` expects. */
export function toRequest(draft: RequirementDraft, options: AnalysisOptions): AnalysisRequest {
  const requirements: ApplicationRequirements = {
    name: draft.name.trim(),
    description: draft.description.trim(),
    expected_users: draft.expected_users.trim() === '' ? null : Number(draft.expected_users),
    traffic_pattern: draft.traffic_pattern === 'unknown' ? null : (draft.traffic_pattern as ApplicationRequirements['traffic_pattern']),
    application_type: (draft.application_type || 'unknown') as ApplicationRequirements['application_type'],
    availability: draft.availability === 'unknown' ? null : (draft.availability as ApplicationRequirements['availability']),
    budget: draft.budget === 'balanced' && !draft.budget ? null : (draft.budget as ApplicationRequirements['budget']),
    preferred_provider: draft.preferred_provider === 'none' ? null : (draft.preferred_provider as ApplicationRequirements['preferred_provider']),
    data_storage: draft.data_storage,
    additional_requirements: draft.additional_requirements.trim() ? draft.additional_requirements.trim() : null,
    template_id: draft.template_id,
  }
  return { requirements, options }
}

export interface ExportEnvelope {
  format: 'json' | 'markdown'
  filename: string
  content: string
  export: { generator: string; schema_version: string; analysis_id: string; [key: string]: unknown }
}
