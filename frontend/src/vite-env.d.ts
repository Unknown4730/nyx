/**
 * Vite client typings.
 *
 * The triple-slash reference supplies `import.meta.env`, the `*.css` and asset
 * module declarations, and `import.meta.glob` — all of which `tsc` needs because
 * `tsconfig.json` uses an explicit `types` allow-list (so ambient packages are not
 * picked up automatically) and enables `noUncheckedSideEffectImports` (so
 * `import './index.css'` must resolve to a declared module).
 *
 * `ImportMetaEnv` below only *adds* NYX's own variables; `interface` declarations
 * merge with the ones shipped by `vite/client`.
 */
/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute API origin. Empty (the default) means same-origin `/api`. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
