import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/ui'
import { ResultsView } from '@/results/ResultsView'
import { useNyx } from '@/state/NyxProvider'

export function ResultsPage() {
  const { result } = useNyx()
  if (!result) {
    return (
      <EmptyState
        title="No analysis to show yet"
        action={
          <Link to="/analyze" className="nyx-btn-primary">
            Start an analysis
          </Link>
        }
      >
        Results appear here after you run an analysis. Saved analyses are listed under Projects.
      </EmptyState>
    )
  }
  return <ResultsView result={result} />
}
