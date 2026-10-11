/**
 * Shared test setup: DOM matchers and a fresh browser-storage state per test.
 */
import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
  window.sessionStorage.clear()
  window.localStorage.clear()
  vi.unstubAllGlobals()
})

// jsdom does not implement scrolling (its stub logs "not implemented") and it cannot
// navigate.  The views scroll on route changes and download through a temporary
// anchor, so both are replaced with no-ops here.  Downloads are asserted through
// URL.createObjectURL and the API calls instead.
window.scrollTo = (() => undefined) as typeof window.scrollTo
Element.prototype.scrollIntoView = () => undefined
const nativeClick = HTMLAnchorElement.prototype.click
HTMLAnchorElement.prototype.click = function click(this: HTMLAnchorElement) {
  if (this.hasAttribute('download')) return
  nativeClick.call(this)
}
if (!URL.createObjectURL) {
  URL.createObjectURL = () => 'blob:nyx-test'
}
if (!URL.revokeObjectURL) {
  URL.revokeObjectURL = () => undefined
}
