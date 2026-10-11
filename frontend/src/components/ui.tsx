/**
 * Small, dependency-free UI primitives shared by every NYX view.
 * Everything is solid colour and built from the design tokens (no gradients).
 */
import type { ReactNode } from 'react'

import type { Tone } from '@/lib/tone'

export function Panel({
  children,
  className = '',
  raised = false,
  as: Tag = 'section',
  labelledBy,
}: {
  children: ReactNode
  className?: string
  raised?: boolean
  as?: 'section' | 'div' | 'article'
  labelledBy?: string
}) {
  return (
    <Tag
      aria-labelledby={labelledBy}
      className={`${raised ? 'nyx-glass-raised' : 'nyx-glass'} nyx-animate-in p-5 sm:p-6 ${className}`}
    >
      {children}
    </Tag>
  )
}

export function SectionHeading({
  id,
  eyebrow,
  title,
  description,
  action,
}: {
  id?: string
  eyebrow?: string
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? <p className="nyx-eyebrow">{eyebrow}</p> : null}
        <h2 id={id} className="mt-1 text-lg font-semibold tracking-tight text-chalk">
          {title}
        </h2>
        {description ? <p className="nyx-subtitle mt-1 max-w-2xl">{description}</p> : null}
      </div>
      {action ? <div className="min-w-0 max-w-full sm:shrink-0">{action}</div> : null}
    </div>
  )
}

export function ToneChip({ tone, children }: { tone: Tone; children?: ReactNode }) {
  return <span className={`nyx-chip ${tone.chip}`}>{children ?? tone.label}</span>
}

export function Chip({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <span className={`nyx-chip border-chalk/[0.12] bg-chalk/[0.04] text-silver ${className}`}>{children}</span>
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="min-w-0">
      <dt className="nyx-eyebrow">{label}</dt>
      <dd className="nyx-metric mt-1 truncate text-xl">{value}</dd>
      {hint ? <dd className="mt-0.5 text-xs text-silver">{hint}</dd> : null}
    </div>
  )
}

/** Horizontal bar for a 0–1 or 0–100 value, with the number always printed beside it. */
export function Meter({
  value,
  max,
  tone,
  label,
}: {
  value: number
  max: number
  tone: Tone
  label: string
}) {
  const safeMax = max > 0 ? max : 1
  const percent = Math.max(0, Math.min(100, (value / safeMax) * 100))
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={safeMax}
      aria-valuenow={Number(value.toFixed(2))}
      className="h-1.5 w-full overflow-hidden rounded-full bg-chalk/[0.08]"
    >
      <div className={`h-full rounded-full ${tone.bar}`} style={{ width: `${percent}%` }} />
    </div>
  )
}

/** Circular score gauge drawn as a solid SVG arc (no gradient). */
export function ScoreGauge({
  score,
  provisional,
  tone,
  caption,
}: {
  score: number | null | undefined
  provisional: boolean
  tone: Tone
  caption: string
}) {
  const radius = 58
  const circumference = 2 * Math.PI * radius
  const hasScore = typeof score === 'number' && Number.isFinite(score)
  const clamped = hasScore ? Math.max(0, Math.min(100, score)) : 0
  const offset = circumference * (1 - clamped / 100)
  return (
    <div className="relative flex h-40 w-40 shrink-0 items-center justify-center">
      <svg viewBox="0 0 140 140" className="absolute inset-0 h-full w-full -rotate-90" aria-hidden="true">
        <circle cx="70" cy="70" r={radius} fill="none" stroke="rgba(244,242,255,0.08)" strokeWidth="10" />
        {hasScore ? (
          <circle
            cx="70"
            cy="70"
            r={radius}
            fill="none"
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            className={`${tone.text} transition-[stroke-dashoffset] duration-700 motion-reduce:transition-none`}
            stroke="currentColor"
          />
        ) : null}
      </svg>
      <div className="text-center">
        <p className="nyx-metric text-4xl font-semibold">{hasScore ? Math.round(score) : '—'}</p>
        <p className="mt-0.5 text-2xs text-silver">{provisional ? 'provisional' : caption}</p>
      </div>
    </div>
  )
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-silver" role="status">
      <span
        aria-hidden="true"
        className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-chalk/20 border-t-primary"
      />
      {label}
    </span>
  )
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <Panel className="text-center">
      <p className="text-base font-semibold text-chalk">{title}</p>
      {children ? <div className="nyx-subtitle mx-auto mt-2 max-w-md">{children}</div> : null}
      {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
    </Panel>
  )
}

export function ErrorNotice({
  title,
  message,
  details = [],
  onRetry,
}: {
  title: string
  message: string
  details?: string[]
  onRetry?: () => void
}) {
  return (
    <div role="alert" className="rounded-2xl border border-coral/35 bg-coral/[0.07] p-4">
      <p className="text-sm font-semibold text-coral">{title}</p>
      <p className="mt-1 text-sm text-chalk/90">{message}</p>
      {details.length > 0 ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-chalk/80">
          {details.map((detail) => (
            <li key={detail}>{detail}</li>
          ))}
        </ul>
      ) : null}
      {onRetry ? (
        <button type="button" onClick={onRetry} className="nyx-btn-secondary mt-3 px-3 py-1.5 text-xs">
          Try again
        </button>
      ) : null}
    </div>
  )
}

export function Disclosure({ children, summary, defaultOpen = false }: { children: ReactNode; summary: string; defaultOpen?: boolean }) {
  return (
    <details className="group rounded-xl border border-chalk/[0.07] bg-obsidian/40 p-3" open={defaultOpen}>
      <summary className="cursor-pointer select-none text-sm font-medium text-chalk marker:text-silver">{summary}</summary>
      <div className="mt-3 text-sm text-silver">{children}</div>
    </details>
  )
}

export function Table({ caption, children }: { caption: string; children: ReactNode }) {
  return (
    <div className="nyx-scroll-x relative -mx-1 rounded-xl border border-chalk/[0.07]">
      <table className="w-full min-w-[32rem] border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  )
}

export const TH = 'border-b border-chalk/[0.08] bg-obsidian/60 px-3 py-2 text-2xs font-semibold uppercase tracking-[0.12em] text-silver'
export const TD = 'border-b border-chalk/[0.05] px-3 py-2.5 align-top text-chalk/90'
