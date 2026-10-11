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
      obsidian: '#08090D',
      carbon: '#101218',
      elevated: '#171A23',
      acid: '#D7FF3F',
      violet: '#A78BFA',
      cyan: '#70E7FF',
      chalk: '#F4F4F0',
      silver: '#9296A3',
      signal: '#FF5B6E',
    })
  })

  it('defines no gradient background images in the Tailwind theme', () => {
    const extend = config.theme?.extend as Record<string, unknown>
    expect(extend.backgroundImage).toBeUndefined()
  })
})
