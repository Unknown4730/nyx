import { describe, expect, it } from 'vitest'

import { EMPTY_DRAFT, normaliseOptions, toDraft, toRequest, toStorageKinds, type RequirementDraft } from '@/types/nyx'
import type { AnalysisOptions } from '@/types/analysis'

const DEFAULTS: AnalysisOptions = { use_ai: true, providers: ['aws', 'gcp', 'azure'], default_provider: null, max_operations_per_view: 14 }

const DRAFT: RequirementDraft = {
  ...EMPTY_DRAFT,
  name: '  Campus portal  ',
  description: 'A campus portal for 300 students with grades and attendance.',
  expected_users: '300',
  traffic_pattern: 'steady',
  availability: 'unknown',
  budget: 'unknown',
  preferred_provider: 'gcp',
  data_storage: ['relational', 'relational', 'not_a_kind', ' object_storage '],
}

describe('draft → request', () => {
  it('trims text, turns "not stated" into null, and drops invalid storage kinds', () => {
    const { requirements } = toRequest(DRAFT, DEFAULTS)
    expect(requirements.name).toBe('Campus portal')
    expect(requirements.expected_users).toBe(300)
    expect(requirements.traffic_pattern).toBe('steady')
    expect(requirements.availability).toBeNull()
    expect(requirements.budget).toBeNull()
    expect(requirements.preferred_provider).toBe('gcp')
    expect(requirements.data_storage).toEqual(['relational', 'object_storage'])
  })

  it('sends null users when the field is blank and no preference when preferred is "none"', () => {
    const { requirements } = toRequest({ ...DRAFT, expected_users: '', preferred_provider: 'none' }, DEFAULTS)
    expect(requirements.expected_users).toBeNull()
    expect(requirements.preferred_provider).toBeNull()
  })

  it('keeps a stated budget', () => {
    expect(toRequest({ ...DRAFT, budget: 'minimize' }, DEFAULTS).requirements.budget).toBe('minimize')
  })

  it('storage kinds are membership-checked, not rewritten', () => {
    expect(toStorageKinds(['Relational', 'none'])).toEqual(['none'])
  })
})

describe('stored session migration', () => {
  it('drops keys the backend would reject instead of sending them', () => {
    const migrated = normaliseOptions(
      { use_ai: false, include_conventional_view: true, providers: ['aws', 'undecided'], max_operations_per_view: 9 },
      DEFAULTS,
    )
    expect(Object.keys(migrated).sort()).toEqual(['default_provider', 'max_operations_per_view', 'providers', 'use_ai'])
    expect(migrated.use_ai).toBe(false)
    expect(migrated.providers).toEqual(['aws'])
    expect(migrated.max_operations_per_view).toBe(9)
  })

  it('falls back to defaults when nothing usable is stored', () => {
    expect(normaliseOptions('garbage', DEFAULTS)).toEqual(DEFAULTS)
    expect(normaliseOptions({ providers: ['undecided'] }, DEFAULTS).providers).toEqual(DEFAULTS.providers)
  })

  it('draft round-trips through toDraft without inventing values', () => {
    const request = toRequest(DRAFT, DEFAULTS).requirements
    const back = toDraft({ ...request, name: request.name, description: request.description } as never)
    expect(back.availability).toBe('unknown')
    expect(back.budget).toBe('unknown')
    expect(back.preferred_provider).toBe('gcp')
    expect(back.expected_users).toBe('300')
    expect(back.data_storage).toEqual(['relational', 'object_storage'])
  })
})
