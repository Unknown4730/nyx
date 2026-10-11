import { useEffect, useRef } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ErrorNotice, Spinner } from '@/components/ui'
import { ResultsView } from '@/results/ResultsView'
import { useNyx } from '@/state/NyxProvider'

export function ProjectPage() {
  const { id = '' } = useParams()
  const { openProject, projectId, result, status, error } = useNyx()
  const requested = useRef<string | null>(null)

  useEffect(() => {
    if (!id || requested.current === id) return
    requested.current = id
    void openProject(id)
  }, [id, openProject])

  if (result && projectId === id) {
    return <ResultsView result={result} />
  }
  if (status !== 'error' || !error) {
    return (
      <div className="py-16">
        <Spinner label="Opening the saved analysis…" />
      </div>
    )
  }
  return (
    <div className="grid gap-4">
      <ErrorNotice
        title="This project could not be opened"
        message={error}
      />
      <Link to="/projects" className="nyx-btn-secondary w-fit">
        Back to projects
      </Link>
    </div>
  )
}
