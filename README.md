# NYX — Rethink your architecture.

**NYX** is an AI-assisted serverless migration and cloud architecture advisor. Describe
an application, and NYX tells you how suitable it is for serverless, shows the current
and proposed architecture on AWS, Google Cloud or Azure, compares relative cost, lists
security and migration concerns, and says plainly what it does not yet know.

It is a **college Cloud Computing lab project (V1)**. It is built to be run locally,
explained and marked. It is not a deployment tool and not a pricing tool.

- **Offline-first.** The deterministic rules engine needs no API key and no paid service.
  The optional AI assist is off unless you configure an OpenAI-compatible endpoint, and
  even then it only proposes requirement values.
- **Explainable.** Every score shows its weighted factors, the evidence behind each one,
  and the inputs that were missing. Missing evidence is never counted as favourable.
- **Honest about scope.** Cost figures are *relative model units* (RICU), not prices. The
  cloud catalogue lists services and their serverless class; it contains no prices.
  NYX does not provision anything.

Read [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for how results are produced,
[`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md) for a 10-minute demonstration script, and
[`docs/audits/NYX_V1_IMPLEMENTATION_AUDIT.md`](docs/audits/NYX_V1_IMPLEMENTATION_AUDIT.md)
for the release audit, its test evidence and known limitations.

---

## What you get

| Area | What works in V1 |
| --- | --- |
| Requirements | Free-text description plus structured fields; five sample applications; field-level validation. |
| Verdict | Score 0–100, band, recommended pattern, factor table, supporting evidence, concerns, missing inputs. Provisional verdicts when evidence is missing. |
| Architecture | Current (serverful) and proposed (serverless-first) blueprints rendered from the analysis graph, with trust boundaries, a component inspector and a text alternative. |
| Cloud services | Each logical component mapped to AWS, Google Cloud and Azure, with serverless class, confidence and differences. |
| Cost | Relative comparison in RICU: fixed, variable and operational shares, line items, sensitivity to traffic. |
| Security | Architecture-level findings with severity and certainty, baseline risks, verification gaps and limits. |
| Migration | Phased plan with activities, exit criteria, risk and effort; per-component changes. |
| Projects | Save, list, reopen, rename and delete analyses (SQLite). Three clearly labelled examples are seeded. |
| Reports | Markdown report and JSON export, for saved projects and for unsaved results. |

## Requirements

- **Python 3.10 or newer** (the backend is tested on 3.11).
- **Node.js 20 or newer** with npm (the frontend is tested on Node 22).
- No database server, no Docker, no cloud account, no API key.

---

## Quick start: macOS or Linux

```bash
# 1. Backend: create a virtual environment and install the pinned dependencies
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt

# 2. Start the API (from the backend folder so the `app` package is found)
cd backend
../.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

In a second terminal:

```bash
# 3. Frontend: install and start the web client
cd frontend
npm ci
npm run dev
```

Open **http://localhost:5173**. The dev server forwards `/api` to the API on port 8000,
so the browser only ever talks to one origin.

## Quick start: Windows (PowerShell)

These are the standard commands for PowerShell 5.1 or PowerShell 7. They are provided
as plain steps; they have not been executed on a Windows machine by the project team.

```powershell
# 1. Backend: virtual environment and dependencies (run from the repository root)
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 2. Start the API (in its own PowerShell window, from the backend folder)
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```powershell
# 3. Frontend (in a second PowerShell window, from the repository root)
cd frontend
npm ci
npm run dev
```

Open **http://localhost:5173**.

If PowerShell refuses to run the activation script, you do not need it: the commands
above call the virtual environment's Python directly. To allow local scripts for your
user only, you can run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

### Single-process mode (one server, one port)

Build the client once, then let the API serve it:

```bash
cd frontend && npm ci && npm run build && cd ..
cd backend
NYX_STATIC_DIR=../frontend/dist ../.venv/bin/python -m uvicorn app.main:app --port 8000
```

On PowerShell: `$env:NYX_STATIC_DIR = "..\frontend\dist"` then the same `uvicorn` command.
Open **http://localhost:8000**. Unknown `/api/...` paths return JSON errors; every other
path returns the web client.

---

## Running the checks

```bash
# Backend: full test suite (fixtures are temporary; nothing touches your database)
cd backend && ../.venv/bin/python -m pytest -q

# Frontend: typecheck, lint, unit and workflow tests, production build
cd frontend
npm run typecheck
npm run lint
npm test
npm run build
```

On PowerShell use `..\.venv\Scripts\python.exe -m pytest -q` from `backend`, and the
same `npm` commands from `frontend`. The exact results of the last release run are in
the audit document.

## Configuration

NYX runs with **no configuration**. Settings are read from environment variables. The
backend does not parse `.env` files; see [`.env.example`](.env.example) for every
variable with its default and purpose.

| Variable | Default | Purpose |
| --- | --- | --- |
| `NYX_DB_PATH` | `backend/data/nyx.sqlite3` | SQLite file for saved projects (relative to the repo root). |
| `NYX_SEED_EXAMPLES` | `1` | Create the three labelled example projects on first start. |
| `NYX_STATIC_DIR` | unset | Serve a built client from the API (single-process mode). |
| `NYX_LOG_LEVEL` | `INFO` | Logging verbosity. |
| `NYX_AI_BASE_URL`, `NYX_AI_API_KEY`, `NYX_AI_MODEL` | empty | Optional OpenAI-compatible endpoint. Leave empty for the rules engine. |
| `NYX_API_PROXY` | `http://127.0.0.1:8000` | Where the Vite dev server forwards `/api`. |

Never commit a real API key. `.env` and `.env.*` (except `.env.example`) are git-ignored.

## API overview

All endpoints are under `/api`. Errors use one envelope:
`{"error": {"code", "message", "details": [...], "retryable"}}`.

| Method and path | Purpose |
| --- | --- |
| `GET /api/health` | Liveness, versions, AI and storage status. |
| `GET /api/meta` | Enumerations, sample templates, scoring bands and weights, cost rates, catalogue summary, input limits. |
| `GET /api/ai/status` | Whether an AI endpoint is configured (never shows the key). |
| `POST /api/analyze` | Run the analysis; returns the full result. Nothing is stored. |
| `POST /api/analyze/export` | Run the analysis and return a `markdown` or `json` report inline. |
| `GET /api/projects` · `POST /api/projects` | List or save projects. |
| `GET /api/projects/stats` | Counts derived from stored rows. |
| `GET/PUT/DELETE /api/projects/{id}` | Reopen, rename or re-run, or delete a project. |
| `GET /api/projects/{id}/export.json` | JSON export envelope (`format`, `filename`, `content`). |
| `GET /api/projects/{id}/report.md` | Markdown report as a file download. |
| `GET /api/projects/{id}/graph?view=&provider=` | One architecture view projected for a provider. |

Interactive documentation is available at **http://localhost:8000/api/docs** while the API runs.

## Repository layout

```
backend/
  app/
    api/          FastAPI routers and the error envelope
    rules/        Deterministic rules: requirements, suitability, cost, security, migration
    services/     Pipeline, catalogue and template loaders, reports, AI provider (optional)
    schemas/      Pydantic models: the analysis contract (nyx.analysis/1)
    database/     SQLite project store
    data/         cloud_services.json (catalogue) and templates.json (samples) — tracked data
  tests/          pytest suite (unit, contract, workflow and data-integrity tests)
  scripts/        export_typescript_schema.py — regenerates frontend/src/types/analysis.ts
frontend/
  src/
    pages/        Home, New analysis, Results, Projects, Project, Method, 404
    results/      Overview, architecture, cloud services, cost, security, migration
    components/   Diagram renderer, layout and shared UI primitives
    state/        Session provider (draft, options, result, projects, backend status)
    lib/          Typed API client, formatting, tone mapping
    types/        analysis.ts (generated from the backend), nyx.ts (hand-written view models)
    test/         Harness, backend-captured fixtures, setup
docs/
  METHODOLOGY.md  How scores, patterns, costs and reviews are produced
  DEMO_GUIDE.md   Demonstration script for the college lab
  audits/         Implementation audit (initial and final)
```

Regenerate the TypeScript contract after changing a backend schema:

```bash
.venv/bin/python backend/scripts/export_typescript_schema.py
```

## Data files

- `backend/app/data/cloud_services.json` — the service catalogue (catalogue version
  2026.10): 81 services across AWS, Google Cloud and Azure, each with an https link,
  category, serverless class and limitations. **It is not a pricing file.**
- `backend/app/data/templates.json` — the five sample applications (template version
  2026.10). A template is a prefilled input; choosing one runs the same engine as typing
  the description.

Both files are required. If either is missing or malformed, the API refuses to start and
logs the reason.

## Troubleshooting

- **“NYX cannot reach its API”** — the backend is not running on port 8000. Start it as
  shown above, then use the status chip in the header to check again.
- **Port already in use** — stop the other process, or choose another port for uvicorn and
  set `NYX_API_PROXY` to match.
- **Empty Projects list** — samples are created on first start. Set `NYX_SEED_EXAMPLES=1`
  and restart, or delete the SQLite file to reset.
- **Windows path errors when running uvicorn** — run the backend command from the
  `backend` folder so the `app` package resolves.

## Known limitations

See the audit document for the complete list. The main ones:

- Scores are rule-based heuristics over the description. Their value depends on how
  specific the description is; the provisional verdict exists so that gaps are visible.
- Cost is a relative model. It does not reflect real prices, discounts, data transfer
  tiers, reserved capacity or currency.
- The security review is architectural. It is not a penetration test or a compliance
  certification.
- No infrastructure is created. NYX never calls a cloud provider.
- The web client is tested with a jsdom workflow suite and a production build; it has
  not been visually verified in a browser by the project team in this release.

## Licence and attribution

Coursework project. All sample data is synthetic. The service names and links are
provider public documentation references, used for comparison only.
