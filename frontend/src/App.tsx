/**
 * Route table for the NYX web client.  Every page reads the shared session state
 * through `useNyx()`; nothing here fetches data directly.
 */
import { Route, Routes } from 'react-router-dom'

import { Layout } from '@/components/Layout'
import { AnalyzePage } from '@/pages/AnalyzePage'
import { HomePage } from '@/pages/HomePage'
import { MethodPage } from '@/pages/MethodPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ProjectPage } from '@/pages/ProjectPage'
import { ProjectsPage } from '@/pages/ProjectsPage'
import { ResultsPage } from '@/pages/ResultsPage'

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="analyze" element={<AnalyzePage />} />
        <Route path="results" element={<ResultsPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:id" element={<ProjectPage />} />
        <Route path="method" element={<MethodPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
