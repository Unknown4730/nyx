import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="grid gap-6 py-12 text-center">
      <p className="nyx-eyebrow">404 · route not found</p>
      <h1 className="nyx-title mx-auto max-w-xl">Nothing is running at this address.</h1>
      <p className="nyx-subtitle mx-auto max-w-md">
        Serverless has a famous rule: somebody still owns the server. Here, nobody does, so there is simply no page. Try the
        dashboard.
      </p>
      <div className="flex justify-center gap-3">
        <Link to="/" className="nyx-btn-primary">
          Go to the dashboard
        </Link>
        <Link to="/analyze" className="nyx-btn-secondary">
          Start an analysis
        </Link>
      </div>
    </div>
  )
}
