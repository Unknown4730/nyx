import { describe, expect, it } from 'vitest'
import { validateDraft } from './pages/AnalyzePage'
import { EMPTY_DRAFT, type MetaPayload, type RequirementDraft } from './types/nyx'
import metaFixture from './test/fixtures/meta.json'

// The fixture is the /api/meta response shape. The frontend validator must use the
// limits it publishes, so these tests fail if the metadata stops carrying them.
const meta = metaFixture as unknown as MetaPayload

function draft(overrides: Partial<RequirementDraft>): RequirementDraft {
  return { ...EMPTY_DRAFT, name: 'Campus portal', description: 'A college attendance portal for staff.', ...overrides }
}

describe('Analyze form validation uses the published limits', () => {
  it('rejects a name shorter than the schema minimum', () => {
    const errors = validateDraft(draft({ name: 'A' }), meta)
    expect(errors['requirements.name']).toBe(`Give the application a name of at least ${meta.limits.name_min_chars} characters.`)
  })

  it('rejects a name longer than the schema maximum', () => {
    const errors = validateDraft(draft({ name: 'x'.repeat((meta.limits.name_max_chars ?? 90) + 1) }), meta)
    expect(errors['requirements.name']).toContain(`at most ${meta.limits.name_max_chars} characters`)
  })

  it('rejects a description shorter than the schema minimum', () => {
    const errors = validateDraft(draft({ description: 'too short' }), meta)
    expect(errors['requirements.description']).toContain(`at least ${meta.limits.description_min_chars} characters`)
  })

  it('accepts values inside the published limits', () => {
    expect(validateDraft(draft({}), meta)).toEqual({})
  })

  it('does not check anything when metadata has not loaded', () => {
    expect(validateDraft(draft({ name: 'A' }), null)).toEqual({})
  })

  it('treats a missing minimum as no check rather than a wrong check', () => {
    const relaxed = { ...meta, limits: { ...meta.limits, name_min_chars: null } } as MetaPayload
    expect(validateDraft(draft({ name: 'A' }), relaxed)).toEqual({})
  })
})
