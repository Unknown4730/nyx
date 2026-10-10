/** Small formatting helpers — numbers and enum labels are shown everywhere. */

const numberFormat = new Intl.NumberFormat('en-US')
const compactFormat = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })

export function num(value: number | null | undefined, fallback = 'not stated'): string {
  return typeof value === 'number' && Number.isFinite(value) ? numberFormat.format(value) : fallback
}

export function compact(value: number | null | undefined, fallback = '—'): string {
  return typeof value === 'number' && Number.isFinite(value) ? compactFormat.format(value) : fallback
}

export function decimal(value: number | null | undefined, digits = 1, fallback = 'not stated'): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : fallback
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

export function signed(value: number, digits = 2): string {
  const fixed = Math.abs(value).toFixed(digits)
  if (value > 0.0001) return `+${fixed}`
  if (value < -0.0001) return `−${fixed}`
  return `±${fixed}`
}

export function minutes(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'not stated'
  if (value < 1) return `${Math.round(value * 60)} s`
  if (value < 90) return `${value.toFixed(value < 10 ? 1 : 0)} min`
  const hours = value / 60
  return `${hours.toFixed(hours < 10 ? 1 : 0)} h`
}

/** `spiky_event_driven` → `Spiky event driven` (sentence case reads calmer than Title Case here). */
export function humanise(value: string | null | undefined, fallback = 'not stated'): string {
  if (!value) return fallback
  const text = value.replace(/_/g, ' ').replace(/-/g, ' ').trim()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function titleCase(value: string | null | undefined, fallback = 'Not stated'): string {
  if (!value) return fallback
  return humanise(value, fallback)
    .split(' ')
    .map((word) => (word.length <= 3 && word === word.toLowerCase() ? word : word.charAt(0).toUpperCase() + word.slice(1)))
    .join(' ')
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return iso
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 45) return 'just now'
  const table: [number, string][] = [
    [86_400 * 30, 'month'],
    [86_400 * 7, 'week'],
    [86_400, 'day'],
    [3600, 'hour'],
    [60, 'minute'],
  ]
  for (const [span, unit] of table) {
    if (seconds >= span) {
      const count = Math.floor(seconds / span)
      return `${count} ${unit}${count === 1 ? '' : 's'} ago`
    }
  }
  return 'just now'
}

export function timestamp(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function truncate(value: string, max = 140): string {
  return value.length <= max ? value : `${value.slice(0, max - 1).trimEnd()}…`
}

/** Filenames must stay safe when they come from user-typed project names. */
export function slugify(value: string, fallback = 'nyx-analysis'): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48)
  return slug || fallback
}
