/**
 * Hand-written types for the descriptive endpoints (`/api/meta`, `/api/ai/status`),
 * for client-only view models.  Everything in the analysis contract lives in
 * `./analysis.ts`, which is generated from the backend Pydantic models.
 */
import type {
  AiStatusPayload,
  AnalysisOptions,
  AnalysisRequest,
  ApplicationRequirements,
  ArchitectureStyle,
  AnalysisResult,
  CloudProvider,
  DataStorageKind,
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
  /** Share of workload weight that may lack evidence before the verdict is withheld. */
  missing_weight_limit: number
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
  name_min_chars: number | null
  name_max_chars: number | null
  description_min_chars: number | null
  description_max_chars: number | null
  additional_requirements_max_chars: number | null
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
  /** Exactly the request options the backend accepts (no legacy or extra flags). */
  options: AnalysisOptions
  result?: AnalysisResult | null
}

/* ------------------------------------------------------- contract runtime mirrors
 * The generated `analysis.ts` describes the contract as *types*.  Validation of
 * stored session data and of form input needs the same members at runtime, so the two
 * mappings below mirror the generated unions.
 *
 * They are keyed by the union itself, which makes them exhaustive by construction:
 * adding a member to a generated union fails to compile until the mapping is updated
 * (missing key), and removing or renaming one is rejected as an unknown key.  A plain
 * array of values would only prove that the entries present are valid — a new member
 * could then be silently dropped at runtime.  These hold memberships only; labels and
 * ordering for the UI still come from `meta.enums.*`, so this is a guard, never a
 * second catalogue of options.
 */

const CLOUD_PROVIDER_MEMBERS = {
  aws: true,
  gcp: true,
  azure: true,
  undecided: true,
} satisfies Record<CloudProvider, true>

const DATA_STORAGE_KIND_MEMBERS = {
  relational: true,
  document: true,
  key_value: true,
  object_storage: true,
  file_share: true,
  cache_session: true,
  search_index: true,
  time_series: true,
  analytical_warehouse: true,
  queue_or_log: true,
  none: true,
  unknown: true,
} satisfies Record<DataStorageKind, true>

/** Own-property lookup keeps membership prototype-safe (`constructor` is not a member). */
function isCloudProvider(value: unknown): value is CloudProvider {
  return typeof value === 'string' && Object.hasOwn(CLOUD_PROVIDER_MEMBERS, value)
}

function isStorageKind(value: unknown): value is DataStorageKind {
  return typeof value === 'string' && Object.hasOwn(DATA_STORAGE_KIND_MEMBERS, value)
}

/**
 * Keep the storage kinds the contract declares and drop everything else.
 *
 * The draft holds text (`string[]`) because a multi-select is a text control, while
 * `ApplicationRequirements.data_storage` is `DataStorageKind[]`.  Blank entries,
 * duplicates and values that are not contract members are removed: an unsupported
 * token must not be sent as though it were a valid enum member, and it must not be
 * rewritten into a different kind either.  The vocabulary shown to users comes from
 * `meta.enums.data_storage`, so anything else cannot arise from the form itself.
 */
export function toStorageKinds(values: readonly string[]): DataStorageKind[] {
  const kinds: DataStorageKind[] = []
  for (const raw of values) {
    const value = raw.trim()
    if (!isStorageKind(value) || kinds.includes(value)) continue
    kinds.push(value)
  }
  return kinds
}

/**
 * Valid providers from a stored value, or `undefined` when nothing usable is left.
 * `undefined` is meaningful: omitting the key lets the backend apply its own
 * default provider set instead of the client asserting an empty one.
 */
function toProviderList(value: unknown, fallback: readonly CloudProvider[] | undefined): CloudProvider[] | undefined {
  const safeFallback = fallback ? [...fallback] : undefined
  if (!Array.isArray(value)) return safeFallback
  const providers: CloudProvider[] = []
  for (const item of value) {
    // `undecided` is a real enum member but not a selectable provider: the backend
    // strips it from `options.providers` and rejects an empty resulting list.
    if (!isCloudProvider(item) || item === 'undecided' || providers.includes(item)) continue
    providers.push(item)
  }
  return providers.length > 0 ? providers : safeFallback
}

function toDefaultProvider(value: unknown, fallback: CloudProvider | null): CloudProvider | null {
  if (value === null) return null // "no preference" is a valid, meaningful value
  if (isCloudProvider(value) && value !== 'undecided') return value
  return fallback
}

/**
 * Turn whatever a session envelope holds into valid `AnalysisOptions`.
 *
 * TypeScript types do not sanitise stored JSON.  A draft written by the previous
 * build carries `include_conventional_view` and friends, and the backend forbids
 * unknown keys (`StrictModel`), so spreading that object into a request produced a
 * 422 for the whole session.  Known keys are copied over the defaults, unknown keys
 * are dropped, and a valid saved selection is kept — the stored draft is migrated,
 * not discarded.
 *
 * The numeric bounds the backend enforces for `max_operations_per_view` are *not*
 * duplicated here: the form control is bound to `meta.limits.max_operations_per_view`
 * and the API remains the authority on its own range.
 */
export function normaliseOptions(stored: unknown, defaults: AnalysisOptions): AnalysisOptions {
  // Nothing stored (or not an object): keep the defaults, copying the provider list
  // so the caller's constant can never be mutated through the returned state.
  if (!stored || typeof stored !== 'object') {
    return { ...defaults, providers: defaults.providers ? [...defaults.providers] : undefined }
  }
  const source = stored as Partial<Record<keyof AnalysisOptions, unknown>>
  const limit = source.max_operations_per_view
  return {
    use_ai: typeof source.use_ai === 'boolean' ? source.use_ai : defaults.use_ai,
    providers: toProviderList(source.providers, defaults.providers),
    default_provider: toDefaultProvider(source.default_provider, defaults.default_provider ?? null),
    max_operations_per_view:
      typeof limit === 'number' && Number.isFinite(limit) && limit > 0 ? limit : defaults.max_operations_per_view,
  }
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
    budget: draft.budget === 'unknown' ? null : (draft.budget as ApplicationRequirements['budget']),
    preferred_provider: draft.preferred_provider === 'none' ? null : (draft.preferred_provider as ApplicationRequirements['preferred_provider']),
    data_storage: toStorageKinds(draft.data_storage),
    additional_requirements: draft.additional_requirements.trim() ? draft.additional_requirements.trim() : null,
    template_id: draft.template_id,
  }
  return { requirements, options }
}

/**
 * Inverse of `toRequest`: turn stored `ApplicationRequirements` back into form
 * state.  Values the backend treats as "not stated" map back to the draft's own
 * sentinels (`''` / `'unknown'` / `'none'`), so reopening a project and saving it
 * again never asserts facts the user did not provide.
 *
 * `budget` maps to `'unknown'` rather than `'balanced'` for the same reason: the
 * backend's `_blank_is_none` validator treats "unknown" as *not stated*, while
 * "balanced" would claim a deliberate preference.
 */
export function toDraft(requirements: ApplicationRequirements): RequirementDraft {
  return {
    name: requirements.name ?? '',
    description: requirements.description ?? '',
    expected_users: requirements.expected_users == null ? '' : String(requirements.expected_users),
    traffic_pattern: requirements.traffic_pattern ?? 'unknown',
    application_type: requirements.application_type ?? 'unknown',
    availability: requirements.availability ?? 'unknown',
    budget: requirements.budget ?? 'unknown',
    preferred_provider: requirements.preferred_provider ?? 'none',
    data_storage: requirements.data_storage ? [...requirements.data_storage] : [],
    additional_requirements: requirements.additional_requirements ?? '',
    template_id: requirements.template_id ?? null,
  }
}

/**
 * Formats `POST /api/analyze/export` accepts.  The endpoint also normalises the
 * aliases `md` / `markdown` / `report` / `json` / `""`; the client only ever sends
 * the canonical pair.
 */
export type ExportFormat = 'json' | 'markdown'

/** `{ format, filename, content }` — what the export endpoints return (`backend/app/api/routes`). */
export interface ExportEnvelope {
  format: ExportFormat
  filename: string
  content: string
}
