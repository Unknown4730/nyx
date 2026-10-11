/**
 * Design-system guards.  Two rules are enforced here so they cannot drift silently:
 *   1. NO GRADIENTS anywhere in the client (CSS functions, Tailwind gradient utilities).
 *   2. The palette tokens match the NYX identity exactly.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import config from '../tailwind.config.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(HERE)
// Gradient functions and Tailwind gradient utilities.  Colour-stop names such as
// `from-*` only mean something inside `bg-gradient-*`, so they are covered by that test.
const GRADIENT = /(linear|radial|conic|repeating-linear|repeating-radial)-gradient|bg-gradient/i

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) return walk(path)
    return /\.(ts|tsx|css|js)$/.test(entry) ? [path] : []
  })
}

describe('design system', () => {
  it('contains no gradient functions or gradient utilities in client source', () => {
    const offenders = walk(SRC)
      .filter((file) => !file.endsWith('design-system.test.ts'))
      .filter((file) => GRADIENT.test(readFileSync(file, 'utf8')))
      .map((file) => file.replace(SRC, 'src'))
    expect(offenders).toEqual([])
  })

  it('defines the Obsidian Glass × Electric Acid palette exactly', () => {
    const colors = (config.theme?.extend as { colors: Record<string, string> }).colors
    expect(colors).toEqual({
      obsidian: '#080911',
      carbon: '#0D1020',
      elevated: '#15182B',
      primary: '#B9A0FF',
      'primary-hover': '#C9B7FF',
      blue: '#73D9FF',
      coral: '#FF8DA1',
      champagne: '#FFC994',
      chalk: '#F4F2FF',
      silver: '#A5A9C5',
      muted: '#777D9C',
    })
  })

  it('uses no green or lime colour anywhere in client source', () => {
    // Lime/green accents were the old identity; they must not return as hex values or
    // as Tailwind green/lime utilities.  The lime hue is also caught by name.
    const GREEN = /#D7FF3F|#E3FF72|\b(text|bg|border|ring|stroke|fill|accent|from|to)-(lime|green|emerald|chartreuse)-\d{2,3}/i
    const offenders = walk(SRC)
      .filter((file) => !file.endsWith('design-system.test.ts'))
      .filter((file) => /\.(tsx|ts|css)$/.test(file) && !file.includes('/test/fixtures/'))
      .filter((file) => GREEN.test(readFileSync(file, 'utf8')))
      .map((file) => file.replace(SRC, 'src'))
    expect(offenders).toEqual([])
  })

  it('defines no gradient background images in the Tailwind theme', () => {
    const extend = config.theme?.extend as Record<string, unknown>
    expect(extend.backgroundImage).toBeUndefined()
  })
})
