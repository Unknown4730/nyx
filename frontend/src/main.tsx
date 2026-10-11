/**
 * NYX web client entry point.
 *
 * `frontend/index.html` mounts this module into `#root`.  The router wraps the
 * session provider, which is created once; every view reads it through `useNyx()`,
 * so the draft, options, current result and backend metadata survive navigation.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from '@/App'
import { NyxProvider } from '@/state/NyxProvider'

import './index.css'

const container = document.getElementById('root')
if (!container) {
  throw new Error('NYX could not start: index.html is missing the #root element.')
}

if (import.meta.env.DEV || typeof window !== 'undefined') {
  // A small, harmless nod for anyone who opens the developer console.
  console.info('NYX · Rethink your architecture. There are no servers here; there is only someone else’s.')
}

createRoot(container).render(
  <StrictMode>
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <NyxProvider>
        <App />
      </NyxProvider>
    </BrowserRouter>
  </StrictMode>,
)
