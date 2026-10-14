# NYX architecture

NYX is two processes in development and one in production-style runs:

- a **FastAPI backend** (`backend/`) that holds all analysis rules and the SQLite project store;
- a **React + Vite web client** (`frontend/`) that collects requirements and renders results;
- optionally, the backend serves the built client itself (single-process mode, `NYX_STATIC_DIR`).

The browser only ever calls same-origin `/api/...` paths. In development, the Vite dev server
forwards them to the backend (`NYX_API_PROXY`, default `http://127.0.0.1:8000`).

No database server, message broker, cloud SDK or external API is required. The optional AI
assist is an OpenAI-compatible HTTP call that only proposes requirement values, and it is off
unless configured.

## Request flow

```
Browser form / sample template
        │  POST /api/analyze  (or POST /api/projects to save)
        ▼
FastAPI route  ── validates the body against the request schema (field-level 422 on failure)
        │
        ▼
AnalysisPipeline  (backend/app/services/pipeline.py)
  1. requirement_extractor   free text + structured fields → ApplicationRequirements,
                             with per-field provenance (stated / template / inferred / default)
                             and assumptions, open questions and limitations
  2. workload_classifier     signals → named workload shape (request/response, batch, …)
  3. component_identifier    workload → logical components and connections
  4. architecture_engine     components → conventional and proposed graphs, layout positions
                             (rules/architecture_layout.py), cloud mappings from the catalogue
  5. serverless_suitability  weighted factors → score, band, outcome, recommended pattern,
                             missing-input handling, provisional verdict below the evidence limit
  6. cost_estimator          relative RICU model: fixed / variable / operational shares, sensitivity
  7. security_analyzer       architecture-level findings with certainty, baseline risks, gaps
  8. migration_planner       phases, exit criteria and per-component changes
  9. ai_provider (optional)  status recorded in `ai`; never replaces the rules
        │
        ▼
AnalysisResult  (schema nyx.analysis/1)  ── returned as JSON
        │
        ├─ saved? → ProjectStore (SQLite, backend/data/nyx.sqlite3) keeps the full result
        └─ export? → report_generator: Markdown report and JSON, wrapped in an export envelope
```

Rules that decide outcomes live in `backend/app/rules/`:

| Module | Decides |
| --- | --- |
| `requirement_rules.py` | How free text maps to requirement signals (keyword rules with stated evidence). |
| `suitability_rules.py` | Factor weights, bands, the missing-weight limit for a firm verdict (0.30), outcome and pattern rules. |
| `cost_rates.py` | RICU rates for each model. Relative units, not prices. |
| `architecture_layout.py` | Node box size (264×124), gaps (132 horizontal, 46 vertical) and the layered placement. |

The services in `backend/app/services/` apply those rules. `labels.py` turns enum values into
readable text for prose and reports, and does not change any machine value.

## Backend layout

```
backend/app/
  main.py            app factory, lifespan (schema init, example seeding), routers, static serving
  config.py          settings from NYX_* environment variables
  api/               routers (analysis, projects, meta, health) and the error envelope (errors.py)
  rules/             deterministic rule tables (see above)
  services/          pipeline and the stages listed above; templates and catalogue loaders; reports
  schemas/           Pydantic models: requirements, analysis result, architecture, reports, AI, common enums
  database/          SQLite project store (ProjectStore)
  seed.py            creates the three example projects (labelled as examples) by running the real pipeline
  data/              cloud_services.json (catalogue, 81 services) and templates.json (five samples), tracked
  core/              shared helpers
backend/tests/       pytest suites (unit, contract, workflow, regression, data integrity)
backend/scripts/     export_typescript_schema.py (regenerates frontend/src/types/analysis.ts)
```

### Data files

- `cloud_services.json`: the service catalogue (version `2026.10`). Services, serverless classes,
  links and limitations. It contains no prices.
- `templates.json`: the five sample applications (version `2026.10`). A template is a prefilled
  requirements input. Choosing one runs the same pipeline as typing a description.

Both are required. If either is missing or malformed, the API refuses to start and logs the reason.

### Storage

SQLite at `NYX_DB_PATH` (default `backend/data/nyx.sqlite3`, git-ignored). The store saves the full
result with each project, so a reopened project shows exactly what was shown when it was saved,
including after a restart. Example projects are marked `example_project` and shown with a *Sample*
label.

## Frontend layout

```
frontend/src/
  App.tsx, main.tsx     routing and bootstrap
  pages/                Home, Analyze (form and samples), Results, Projects, Project, Method, 404
  results/              Overview, Architecture, Services, Cost, Security, Migration panels
  components/           ArchitectureDiagram (SVG renderer and layout helpers), Layout, ui primitives
  state/NyxProvider.tsx session state: draft, options, meta, current result, projects, backend status
  lib/api.ts            typed client: one error shape (NyxApiError), timeouts, unreachable detection
  lib/format.ts, tone.ts  formatting and colour/label mapping for display only
  types/analysis.ts     generated from the backend schema; nyx.ts holds hand-written view models
  index.css, tailwind   design tokens (obsidian, carbon, violet, blue, coral, champagne, chalk, silver, muted)
  test/                 jsdom harness and backend-captured fixtures
```

Principles enforced in code and tests:

- The frontend renders scores, outcomes, costs and findings from the API. It does not compute them.
- No gradients (`design-system.test.ts` scans the source). No green or lime accents.
- Glass surfaces have solid fallbacks; reduced-motion and reduced-transparency preferences are honoured.
- Colour is never the only carrier of meaning: labels, icons or text accompany each state.

## Architecture diagram

The server computes positions (`architecture_layout.py`) and ships them in the graph. The client
draws boxes on the same 264×124 grid. Labels wrap onto up to two lines; a name is shortened only
when it still does not fit, and the full name is in the tooltip and the accessible label.
A text alternative lists the same components and connections for screen readers.

## Deliberate boundaries

- NYX never calls a cloud provider and never provisions anything.
- The optional AI assist only proposes requirement values. Those values are scored by the same
  rules as typed input, and the result records that AI was used. The rules are never replaced.
- The same analysis input always yields the same result (`analysis_id`, timestamps and
  `duration_ms` aside).
