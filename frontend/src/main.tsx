/**
 * NYX web client entry point.
 *
 * `frontend/index.html` mounts `/src/main.tsx` into `#root`.  The provider is
 * created once here and every view reads it through `useNyx()`, so the session
 * state (draft, options, current result, backend metadata) survives navigation.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from '@/App'
import { NyxProvider } from '@/state/NyxProvider'

import './index.css'

const container = document.getElementById('root')
if (!container) {
  throw new Error('NYX could not start: index.html is missing the #root element.')
}

createRoot(container).render(
  <StrictMode>
    <NyxProvider>
      <App />
    </NyxProvider>
  </StrictMode>,
)
