import { useMemo, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { EmptyState, ErrorNotice, Panel, SectionHeading, Spinner } from '@/components/ui'
import { useAiAvailability, useNyx } from '@/state/NyxProvider'
import type { EnumOption, MetaPayload, RequirementDraft, TemplateCard } from '@/types/nyx'

/** Option label from the backend vocabulary; the "unknown" member reads as "Not stated". */
function labelFor(option: EnumOption): string {
  return option.value === 'unknown' ? 'Not stated' : option.label
}

function withNotStated(options: EnumOption[] | undefined, notStatedLabel = 'Not stated'): EnumOption[] {
  const list = options ?? []
  const hasUnknown = list.some((item) => item.value === 'unknown')
  return hasUnknown ? list.map((item) => (item.value === 'unknown' ? { ...item, label: notStatedLabel } : item)) : [{ value: 'unknown', label: notStatedLabel }, ...list]
}

/**
 * Client-side checks use the limits the API publishes in `/api/meta` (derived there
 * from the schema), so the form and the server cannot disagree.  Without metadata the
 * form is disabled and nothing is checked here; the API still validates everything.
 */
export function validateDraft(draft: RequirementDraft, meta: MetaPayload | null): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!meta) return errors
  const limits = meta.limits
  const name = draft.name.trim()
  const description = draft.description.trim()
  const additional = draft.additional_requirements.trim()

  if (limits.name_min_chars != null && name.length < limits.name_min_chars) {
    errors['requirements.name'] = `Give the application a name of at least ${limits.name_min_chars} characters.`
  } else if (limits.name_max_chars != null && name.length > limits.name_max_chars) {
    errors['requirements.name'] = `The name can be at most ${limits.name_max_chars} characters.`
  }

  if (limits.description_min_chars != null && description.length < limits.description_min_chars) {
    errors['requirements.description'] = `Describe the application in at least ${limits.description_min_chars} characters.`
  } else if (limits.description_max_chars != null && description.length > limits.description_max_chars) {
    errors['requirements.description'] = `The description can be at most ${limits.description_max_chars.toLocaleString()} characters.`
  }

  if (draft.expected_users.trim() !== '') {
    const value = Number(draft.expected_users)
    if (!Number.isInteger(value) || value < 1) errors['requirements.expected_users'] = 'Expected users must be a whole number of at least 1, or left blank.'
  }

  if (limits.additional_requirements_max_chars != null && additional.length > limits.additional_requirements_max_chars) {
    errors['requirements.additional_requirements'] = `Additional requirements can be at most ${limits.additional_requirements_max_chars.toLocaleString()} characters.`
  }
  return errors
}

function Select({
  id,
  label,
  value,
  options,
  onChange,
  error,
  hint,
}: {
  id: string
  label: string
  value: string
  options: EnumOption[]
  onChange: (value: string) => void
  error?: string
  hint?: string
}) {
  return (
    <div>
      <label htmlFor={id} className="nyx-label">
        {label}
      </label>
      <select
        id={id}
        className="nyx-field"
        value={value}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {labelFor(option)}
          </option>
        ))}
      </select>
      {hint && !error ? (
        <p id={`${id}-hint`} className="nyx-hint">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-xs text-signal">
          {error}
        </p>
      ) : null}
    </div>
  )
}

function TemplateCards({ templates, onUse, activeId }: { templates: TemplateCard[]; onUse: (id: string) => void; activeId: string | null }) {
  if (templates.length === 0) {
    return <EmptyState title="No sample templates were returned by the API">Describe your own application in the form below.</EmptyState>
  }
  return (
    <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Sample applications">
      {templates.map((template) => (
        <li key={template.id}>
          <article className={`nyx-glass-raised flex h-full flex-col p-5 ${activeId === template.id ? 'ring-1 ring-acid/50' : ''}`}>
            <p className="nyx-eyebrow">Sample</p>
            <h3 className="mt-1 text-base font-semibold text-chalk">{template.name}</h3>
            <p className="mt-1 text-sm text-silver">{template.tagline}</p>
            <p className="mt-3 flex-1 text-xs leading-relaxed text-chalk/75">{template.summary}</p>
            {template.highlights.length ? (
              <ul className="mt-3 flex flex-wrap gap-1.5">
                {template.highlights.map((item) => (
                  <li key={item} className="rounded-chip border border-chalk/10 px-2 py-0.5 text-2xs text-silver">
                    {item}
                  </li>
                ))}
              </ul>
            ) : null}
            <p className="mt-3 text-2xs text-silver">{template.expected_outcome_hint}</p>
            <button type="button" className="nyx-btn-secondary mt-4 w-full" onClick={() => onUse(template.id)}>
              Use “{template.name}”
            </button>
          </article>
        </li>
      ))}
    </ul>
  )
}

export function AnalyzePage() {
  const navigate = useNavigate()
  const { meta, draft, patchDraft, resetDraft, applyTemplate, options, patchOptions, run, status, error, fieldErrors } = useNyx()
  const ai = useAiAvailability()
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({})
  const formRef = useRef<HTMLFormElement | null>(null)

  const enums = meta?.enums
  const storageOptions = useMemo(() => (enums?.data_storage ?? []).filter((item) => item.value !== 'unknown'), [enums])
  const activeTemplate = draft.template_id
  const running = status === 'running'
  const serverErrors = fieldErrors
  const errorFor = (key: string) => clientErrors[key] ?? serverErrors[key]

  function setField<K extends keyof RequirementDraft>(key: K, value: RequirementDraft[K]) {
    patchDraft({ [key]: value } as Partial<RequirementDraft>)
    // A hand edit makes the form no longer exactly the template, so the label goes.
    if (key !== 'template_id' && activeTemplate) patchDraft({ template_id: null })
  }

  function toggleStorage(value: string) {
    const current = new Set(draft.data_storage)
    if (current.has(value)) current.delete(value)
    else current.add(value)
    setField('data_storage', [...current])
  }

  function useTemplate(id: string) {
    applyTemplate(id)
    setClientErrors({})
    formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const problems = validateDraft(draft, meta)
    setClientErrors(problems)
    if (Object.keys(problems).length > 0) {
      const first = formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')
      first?.focus()
      return
    }
    const next = await run()
    if (next) navigate('/results')
  }

  return (
    <div className="grid gap-8">
      <header className="grid gap-3">
        <p className="nyx-eyebrow">New analysis</p>
        <h1 className="nyx-title">Describe the system. Read the verdict.</h1>
        <p className="nyx-subtitle max-w-2xl">
          Choose a sample to start from, or describe your own application. Every result is produced by the same deterministic
          rules, and each conclusion shows the evidence it rests on.
        </p>
      </header>

      <section aria-labelledby="samples-heading" className="grid gap-4">
        <SectionHeading id="samples-heading" eyebrow="Start from a sample" title="Sample applications" description="Samples are prefilled inputs, not stored answers. Running one performs a fresh analysis." />
        {meta ? (
          <TemplateCards templates={meta.templates} onUse={useTemplate} activeId={activeTemplate} />
        ) : (
          <p className="text-sm text-silver">Samples load once the API is reachable.</p>
        )}
      </section>

      <Panel labelledBy="form-heading">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <SectionHeading id="form-heading" eyebrow="Requirements" title="Your application" description="Anything you leave as “Not stated” is not assumed. Missing inputs lower confidence and are listed in the result." />
          <button type="button" className="nyx-btn-ghost" onClick={() => { resetDraft(); setClientErrors({}) }}>
            Clear form
          </button>
        </div>

        {!meta ? (
          <div className="mt-5">
            <ErrorNotice title="The form needs the API" message="NYX could not read its vocabularies from /api/meta. Start the backend, then retry." />
          </div>
        ) : null}

        <form ref={formRef} noValidate onSubmit={handleSubmit} className="mt-6 grid gap-6" aria-busy={running}>
          <fieldset className="grid gap-5 md:grid-cols-2" disabled={!meta || running}>
            <legend className="sr-only">Application details</legend>
            <div className="md:col-span-1">
              <label htmlFor="req-name" className="nyx-label">
                Application name
              </label>
              <input
                id="req-name"
                className="nyx-field"
                value={draft.name}
                maxLength={meta?.limits.name_max_chars ?? undefined}
                placeholder="For example: Campus attendance portal"
                aria-invalid={Boolean(errorFor('requirements.name'))}
                aria-describedby={errorFor('requirements.name') ? 'req-name-error' : undefined}
                onChange={(event) => setField('name', event.target.value)}
              />
              {errorFor('requirements.name') ? (
                <p id="req-name-error" className="mt-1.5 text-xs text-signal">
                  {errorFor('requirements.name')}
                </p>
              ) : null}
            </div>
            <div>
              <Select
                id="req-type"
                label="Application type"
                value={draft.application_type}
                options={withNotStated(enums?.application_type)}
                onChange={(value) => setField('application_type', value)}
                error={errorFor('requirements.application_type')}
              />
            </div>
            <div className="md:col-span-2">
              <div className="flex items-baseline justify-between gap-3">
                <label htmlFor="req-description" className="nyx-label">
                  Description
                </label>
                <span className="font-mono text-2xs text-silver" aria-live="polite">
                  {draft.description.trim().length.toLocaleString()}
                  {meta?.limits.description_max_chars != null ? ` / ${meta.limits.description_max_chars.toLocaleString()}` : ''}
                </span>
              </div>
              <textarea
                id="req-description"
                rows={6}
                className="nyx-field min-h-[9rem] leading-relaxed"
                value={draft.description}
                placeholder="What does it do, who uses it, how busy is it, which data does it keep, and what happens when demand spikes?"
                aria-invalid={Boolean(errorFor('requirements.description'))}
                aria-describedby={errorFor('requirements.description') ? 'req-description-error' : 'req-description-hint'}
                onChange={(event) => setField('description', event.target.value)}
              />
              {errorFor('requirements.description') ? (
                <p id="req-description-error" className="mt-1.5 text-xs text-signal">
                  {errorFor('requirements.description')}
                </p>
              ) : (
                <p id="req-description-hint" className="nyx-hint">
                  The more specific you are about load, state, runtime length and data, the more the result can say.
                </p>
              )}
            </div>
            <div>
              <label htmlFor="req-users" className="nyx-label">
                Expected users
              </label>
              <input
                id="req-users"
                type="number"
                inputMode="numeric"
                min={1}
                step={1}
                className="nyx-field"
                value={draft.expected_users}
                placeholder="Leave blank if not known"
                aria-invalid={Boolean(errorFor('requirements.expected_users'))}
                aria-describedby={errorFor('requirements.expected_users') ? 'req-users-error' : undefined}
                onChange={(event) => setField('expected_users', event.target.value)}
              />
              {errorFor('requirements.expected_users') ? (
                <p id="req-users-error" className="mt-1.5 text-xs text-signal">
                  {errorFor('requirements.expected_users')}
                </p>
              ) : null}
            </div>
            <Select
              id="req-traffic"
              label="Traffic pattern"
              value={draft.traffic_pattern}
              options={withNotStated(enums?.traffic_pattern)}
              onChange={(value) => setField('traffic_pattern', value)}
              hint="Steady, office-hours, scheduled bursts or unpredictable spikes."
            />
            <Select
              id="req-availability"
              label="Availability expectation"
              value={draft.availability}
              options={withNotStated(enums?.availability)}
              onChange={(value) => setField('availability', value)}
            />
            <Select
              id="req-budget"
              label="Budget preference"
              value={draft.budget}
              options={withNotStated(enums?.budget)}
              onChange={(value) => setField('budget', value)}
            />
            <Select
              id="req-provider"
              label="Preferred cloud provider"
              value={draft.preferred_provider}
              options={[{ value: 'none', label: 'No preference' }, ...(enums?.provider ?? [])]}
              onChange={(value) => setField('preferred_provider', value)}
              hint="Chooses which provider is shown first. All three are always compared."
            />
          </fieldset>

          <fieldset disabled={!meta || running}>
            <legend className="nyx-label">Data storage</legend>
            <p className="nyx-hint mt-0 mb-3">Tick every kind of data the application keeps.</p>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {storageOptions.map((option) => {
                const checked = draft.data_storage.includes(option.value)
                return (
                  <label
                    key={option.value}
                    className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 text-sm transition-colors ${checked ? 'border-acid/50 bg-acid/[0.07] text-chalk' : 'border-chalk/10 bg-obsidian/50 text-silver hover:text-chalk'}`}
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-[#D7FF3F]"
                      checked={checked}
                      onChange={() => toggleStorage(option.value)}
                    />
                    {option.label}
                  </label>
                )
              })}
            </div>
          </fieldset>

          <fieldset disabled={!meta || running} className="grid gap-5">
            <legend className="sr-only">Additional detail</legend>
            <div>
              <label htmlFor="req-additional" className="nyx-label">
                Additional requirements <span className="font-normal text-silver">(optional)</span>
              </label>
              <textarea
                id="req-additional"
                rows={3}
                className="nyx-field"
                value={draft.additional_requirements}
                placeholder="Compliance, retention, integrations, or constraints the description does not cover."
                aria-invalid={Boolean(errorFor('requirements.additional_requirements'))}
                onChange={(event) => setField('additional_requirements', event.target.value)}
              />
              {errorFor('requirements.additional_requirements') ? (
                <p className="mt-1.5 text-xs text-signal">{errorFor('requirements.additional_requirements')}</p>
              ) : null}
            </div>
            <div className="rounded-xl border border-chalk/[0.08] bg-obsidian/50 p-4">
              <label className="flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 accent-[#A78BFA]"
                  checked={options.use_ai}
                  disabled={!ai.available}
                  onChange={(event) => patchOptions({ use_ai: event.target.checked })}
                />
                <span>
                  <span className="font-medium text-chalk">Use AI assist to read the description</span>
                  <span className="mt-1 block text-xs text-silver">
                    {ai.available
                      ? 'The model may only propose requirement values. Scoring, cost and security stay rule-based.'
                      : `Unavailable: ${ai.reason}`}
                  </span>
                </span>
              </label>
            </div>
          </fieldset>

          {error ? <ErrorNotice title="The analysis did not run" message={error} details={Object.values(serverErrors).slice(0, 6)} /> : null}

          <div className="flex flex-col gap-3 border-t border-chalk/[0.07] pt-5 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-silver">
              {running ? <Spinner label="Running the rules engine. This usually takes a second or two." /> : 'Nothing is saved until you choose “Save project”.'}
            </p>
            <button type="submit" className="nyx-btn-primary min-w-[12rem]" disabled={!meta || running}>
              {running ? 'Analysing…' : 'Run analysis'}
            </button>
          </div>
        </form>
      </Panel>
    </div>
  )
}
