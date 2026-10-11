# NYX V1 implementation audit

| | |
| --- | --- |
| Product | NYX — AI-assisted serverless migration and cloud architecture advisor |
| Release | V1 (college Cloud Computing lab) |
| Repository | `Unknown4730/nyx`, branch `arena/1435d4fc-nyx` |
| Baseline | `main` at `e0ada1db6a47126430f44e887afcadb8fb99dbcf` (PRs #1–#3 merged) |
| Engine | rule pack `2026.10`, catalogue `2026.10`, cost model `2026.10`, schema `nyx.analysis/1` |
| Audit type | Self-audit by the implementing agent, with reproducible test evidence |
| Independent review | **Not performed.** No external reviewer has approved this release. |

---

## 1. Release status

**Status: V1 is functionally complete for the college demonstration, with the limitations
in section 7.** The backend starts, every documented endpoint was exercised, the frontend
builds and passes its typecheck, lint and 46 workflow and unit tests, and the built client
is served by the backend. The main workflow (requirements → analysis → results → save →
reopen → export) works in the browser-facing code paths that the tests drive, and over HTTP
against the running service.

What is **not** claimed:

- Visual design quality has not been checked in a real browser. The sandbox used for this
  release has no browser, so the design was verified by build output, token tests and the
  absence of gradients, not by looking at screenshots. A human review of the screens is
  recommended before the demo.
- The PowerShell instructions were not executed on Windows.
- No independent reviewer approved the release.

## 2. What was built or repaired

### 2.1 Backend

- **Data files restored as required runtime data.** `backend/app/data/cloud_services.json`
  (81 services, three providers, https links, serverless classes, limitations; explicitly
  *not a pricing file*) and `backend/app/data/templates.json` (five sample applications).
- **Typed loader errors.** Missing, unreadable or malformed catalogue or template files raise
  `CatalogDataError` / `TemplateDataError` with the file path and the reason. The service
  refuses to start (verified: startup with a missing catalogue stops with that message).
- **Metadata derived from the schema.** `/api/meta` input limits (name, description,
  additional requirements) are read from the Pydantic field constraints, not copied. The
  missing-weight limit (0.30) is published so the UI does not duplicate it.
- **Markdown report escaping.** Pipes and line breaks in user text cannot add or break table
  columns (`_c()` in `report_generator.py`).
- **Unknown `/api/...` paths return JSON 404 envelopes**, not the single-page shell.
- **Export contract.** `AnalysisExportRequest` is now emitted by the TypeScript generator.
- **Suitability decision recorded.** The unreachable component override at 0.34 was removed
  (behaviour preserved; see 3.2). `_spike_factor` documents its 1.35 default as an assumption.

### 2.2 Frontend

The Cycle 0a shell (which listed the requirements form, results, architecture workspace and
saving as "Not built yet") was replaced by a complete client:

- **Home** — product line, live API and AI status, recent projects, the three-step method.
- **New analysis** — five sample applications from `/api/meta`; a form built from the backend's
  vocabularies; client checks that mirror the API limits; backend field errors mapped to the
  control they belong to; AI toggle disabled honestly when no endpoint is configured.
- **Results** — header with verdict, provenance, save and export; tabs for Overview,
  Architecture, Cloud services, Cost model, Security and Migration; keyboard-navigable tabs.
- **Architecture** — conventional and proposed blueprints drawn from the graph's own layout
  coordinates, trust boundaries, provider switch (AWS, Google Cloud, Azure), zoom, a component
  inspector, and a text alternative with every component and connection.
- **Projects** — list with sample/saved labelling, filters, open, delete with confirmation,
  and the stored statistics.
- **Method** — score bands, weights, limits and cost model, all read from `/api/meta`.
- **Visual identity** — "Obsidian Glass × Electric Acid" tokens exactly as specified (obsidian
  `#08090D`, carbon `#101218`, elevated `#171A23`, acid `#D7FF3F`, violet `#A78BFA`, cyan
  `#70E7FF`, chalk `#F4F4F0`, silver `#9296A3`, signal `#FF5B6E`). **No gradients**: no gradient
  functions, no gradient utilities, no gradient background images (enforced by a test; see 4).
- **Dependencies trimmed.** Unused React Flow, Recharts, class-variance-authority,
  tailwind-merge, clsx and lucide-react were removed.

### 2.3 Tooling and documentation

- ESLint flat configuration added (the `lint` script previously had no config).
- Vitest setup file added (`frontend/src/test/setup.ts`), which the configuration already referenced.
- `README.md` rewritten: quick starts for macOS/Linux and Windows PowerShell, configuration,
  API overview, repository layout, troubleshooting and known limitations.
- `docs/METHODOLOGY.md` — how scores, patterns, costs, security and migration are produced,
  generated from the rule values in the code.
- `docs/DEMO_GUIDE.md` — a 10-minute demonstration script with the real outcomes of each sample.
- `.env.example` — every variable matches `config.py`; Docker and nginx references removed; a
  note that the backend does not read `.env` files.

## 3. Audit findings and disposition

Severity: **P0** blocks the core product; **P1** a defect a user or examiner would hit;
**P2** a correctness, contract or maintainability risk; **P3** cosmetic or documentation.

| # | Sev | Finding (as found at baseline) | Disposition |
| --- | --- | --- | --- |
| F01 | P0 | `backend/app/data/` missing: `cloud_services.json` and `templates.json` absent, so the backend could not load its catalogue and the test suite failed at collection. | **Fixed.** Files restored and validated; startup refuses with a clear message if they go missing. |
| F02 | P0 | Frontend was a Cycle 0a shell: no requirements form, results, architecture, or saving. | **Fixed.** Complete client built (section 2.2). |
| F03 | P1 | `.gitignore` rule `data/` also hid `backend/app/data/`, so the required data files could not be committed. | **Fixed.** Anchored to `/data/`; `backend/data/` (database) stays ignored. Confirmed with `git check-ignore`: the data files are no longer ignored. |
| F04 | P1 | `frontend/src/test/setup.ts` referenced by Vitest and TypeScript configuration but absent. | **Fixed.** Added, with jsdom shims. |
| F05 | P1 | Sample templates did not exercise the engine as intended: the file-processing template gave a confident verdict with no evidence gaps, and college-attendance and file-processing produced the same outcome. Five backend tests failed. | **Fixed by honest template wording.** The file-processing template now leaves traffic, statelessness and availability unstated, so the engine returns a provisional verdict (score 53.9, provisional 67.0, further assessment required). The verdict is produced by the rules, not by the template. The five tests pass unchanged. |
| F06 | P1 | JSON export link downloaded the API's envelope (`{format, filename, content}`) instead of the report. | **Fixed.** The client fetches the envelope and saves its `content`. Test pins this. |
| F07 | P1 | Tailwind configuration and CSS defined gradient tokens (`nyx-mesh`, `nyx-grid`, `nyx-fade`, `nyx-line`), violating the no-gradient rule. Palette did not match the specification. | **Fixed.** Gradients removed; tokens replaced with the specified palette; guard tests added. |
| F08 | P2 | Frontend duplicated suitability band thresholds (78/62/45) in its tone module. | **Fixed.** Colour follows the backend's returned outcome. |
| F09 | P2 | Frontend hard-coded the missing-weight limit (0.30) and input limits. | **Fixed.** Published by `/api/meta` (`missing_weight_limit`, `limits.*`) and used by the UI. |
| F10 | P2 | Component missing-weight override at 0.34 could never fire, because the only component factor that can lack evidence is `duration` (0.26). | **Fixed (behaviour-preserving).** Branch removed with an explanatory docstring. `test_suitability_regression.py` checks all 5,120 component trait combinations and pins the maximum missing weight at 0.26. |
| F11 | P2 | Earlier review said `_spike_factor` was unused. | **Corrected.** It is used by `SuitabilityService.assess`. Its docstring now documents the 1.35 default as an assumption, and a test checks the value. |
| F12 | P2 | Test `test_band_boundaries_are_exhaustive_and_monotonic` claimed exhaustiveness it did not have, and no test covered every boolean trait. | **Fixed.** Renamed to `…ordered_and_monotonic`; new exhaustive trait test covers all seven booleans × eight runtimes × five durations. |
| F13 | P2 | Markdown report tables interpolated user text without escaping; a pipe or newline in a name could corrupt the table. | **Fixed.** Escaped; test checks every table block keeps a constant column count. |
| F14 | P2 | Unknown `/api/...` paths returned the single-page HTML shell rather than a JSON 404. | **Fixed.** `test_static_hosting.py`. |
| F15 | P2 | Catalogue and template loaders failed with raw exceptions and accepted structurally invalid files. | **Fixed.** Typed errors, structural validation, and 21 data-integrity tests. |
| F16 | P2 | `frontend/src/types/nyx.ts` hand-copied `AnalysisExportRequest`, and `ExportEnvelope` described a field the API does not send. | **Fixed.** Generated from the backend; envelope type corrected. |
| F17 | P2 | Dead condition in `toRequest` (`budget`). | **Fixed.** |
| F18 | P2 | `pyproject.toml` declared Python ≥3.10. | **Verified and kept.** The code uses a 3.10-compatible `StrEnum`. |
| F19 | P2 | Unused frontend dependencies (React Flow, Recharts, CVA, tailwind-merge, clsx, lucide-react); `lint` script with no configuration. | **Fixed.** Removed; ESLint configuration added; lint passes with zero warnings. |
| F20 | P2 | React Router future-flag warnings in the test output. | **Fixed.** Flags opted in. |
| F21 | P3 | README was a six-byte stub; no `docs/`; `.env.example` mentioned Docker Compose and nginx, which do not exist here. | **Fixed.** README, methodology, demo guide and corrected `.env.example`. |
| F22 | P3 | Security rules and the suitability module cited `docs/PROJECT_REPORT.md`, which did not exist. | **Fixed.** Citations point to `docs/METHODOLOGY.md`, which exists. |
| F23 | P3 | Leftover "Cycle 0a" and "Read-only in this cycle" wording in the UI and types. | **Fixed.** Removed (grep-verified). |

**Open items carried into V1 (not defects of the release, but recorded):**

- O1: No browser-based visual or accessibility audit (see section 7).
- O2: The graph endpoint returns HTTP 200 with an error object for an unknown view. The route's
  pattern validation rejects unknown views with 422 before this branch is reachable, so the
  branch is dead code. It is left in place rather than changed without a test need.
- O3: One third-party deprecation warning (anyio, from the Starlette test client) appears in the
  backend test output. It is outside the project's code.

## 4. Test results

All commands were run in this sandbox at the end of the release work. Versions: Python 3.11.2
(virtual environment at `/tmp/venv`, pinned to `backend/requirements.txt`), Node v22.22.3,
npm with the lock file.

### 4.1 Backend

```bash
cd backend
python -m pytest -q
```

- Result: **exit code 0**. With the summary line enabled (`-o addopts=""`) the run reports
  **270 passed, 1 warning in 8.42 s** (the warning is third-party; see O3).
- Coverage of the suite: API contract and error envelopes, analysis pipeline, requirement
  extraction, suitability (including the regression and exhaustive tests), cost model,
  security review, migration plan, architecture graph, cloud mapping, reports and escaping,
  project persistence and lifecycle, data integrity, static hosting, AI provider behaviour
  (with stub providers only; no network).
- Earlier baseline (before this work): collection failed on the missing catalogue; after the
  data was restored, five tests failed on verdict expectations (F05). All now pass.

### 4.2 Frontend

```bash
cd frontend
npm ci
npm run typecheck     # tsc --noEmit
npm run lint          # eslint src --max-warnings=0
npm test              # vitest run
npm run build         # tsc --noEmit && vite build
```

| Command | Result |
| --- | --- |
| `npm ci` | Completed without errors (407 packages at first install; unused dependencies were removed afterwards with `npm uninstall`). |
| `npm run typecheck` | exit 0 |
| `npm run lint` | exit 0, zero warnings |
| `npm test` | exit 0 — **Test Files 5 passed (5); Tests 46 passed (46)**; no console warnings |
| `npm run build` | exit 0 — `dist/index.html` 0.78 kB; CSS 27.38 kB (gzip 5.85 kB); JS 263.00 kB (gzip 80.19 kB) |

Frontend test files:

- `src/lib/api.test.ts` — error-envelope parsing, network and gateway failures, not-found, the
  export envelope contract, Markdown as text, field-error mapping. (8 tests)
- `src/types/nyx.test.ts` — draft ↔ request conversion, storage kinds, stored-session migration.
  (7 tests)
- `src/design-system.test.ts` — no gradient functions or utilities in client source; exact palette;
  no gradient background images in the theme. (3 tests)
- `src/components/ArchitectureDiagram.test.tsx` — layout bounds and origin shifting, edge anchoring,
  label clipping, a forgotten node still drawn, keyboard selection, trust boundaries and connections
  rendered. (10 tests)
- `src/app.test.tsx` — the real App, provider and router against backend-captured fixtures:
  offline status, honest 404, sample → run → verdict, client validation, backend 422 mapped to the
  field, safe error text, keyboard tab navigation, all six sections, Current and Proposed views,
  save, export of unsaved (AI off) and saved results, projects list and filter, reopen, missing
  project message, delete confirmation, method page read from metadata. (18 tests)

Fixtures in `src/test/fixtures/` (`meta.json`, `sample-analysis.json`) were captured from the
backend's real responses, not written by hand.

### 4.3 Live integration (running service)

Commands run against a live `uvicorn` process serving the built client:

```bash
cd backend
NYX_DB_PATH=<tmp>.sqlite3 NYX_STATIC_DIR=../frontend/dist python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- `GET /` and `GET /analyze`, `GET /projects/abc` → `200 text/html` (SPA shell).
- `GET /api/nope` → `404 application/json` with `error.code = HTTP_404`.
- `GET /api/health`, `GET /api/meta` → `200`; limits `name_min_chars=2`, `description_min_chars=10`,
  `missing_weight_limit=0.3`; five templates.
- All five sample templates analysed through `POST /api/analyze` with the outcomes in section 5.
- Invalid input: `POST /api/analyze` with a two-character name and a short description → `422` with
  two field-scoped details.
- Full project lifecycle: create → reopen → `export.json` (envelope) → `report.md` → graph
  (`proposed`, `gcp`) → rename → delete → reopen returns `404 PROJECT_NOT_FOUND`.
- Startup with the catalogue path pointed at a missing file: refused with
  `CatalogDataError: Required service catalogue not found …`.

Vite development server (`npm run dev`, port 5173): `/analyze` → 200 shell; `/api/health` and
`/api/meta` proxied to the API → 200 JSON; `/src/main.tsx` → 200; `/favicon.svg` → 200.

### 4.4 Determinism

With AI off, the same requirements produce identical results except for `analysis_id`,
`created_at` and `duration_ms` (checked by running the same template twice and comparing the
JSON).

## 5. Verified outcomes (AI off)

| Sample | Score | Verdict | Pattern | Proposed ÷ conventional (model) | Missing inputs |
| --- | --- | --- | --- | --- | --- |
| College Attendance Portal | 69.0 | Suitable with modifications | Serverless where suitable | 0.62 | 1 |
| Online Examination Platform | 78.1 | Strong candidate | Serverless first | 0.66 | 1 |
| Online Store | 77.1 | Suitable with modifications | Serverless where suitable | 1.00 | 1 |
| Food Delivery Platform | 75.3 | Suitable with modifications | Serverless where suitable | 1.07 | 1 |
| Document Processing Pipeline | 53.9 (provisional 67.0) | Further assessment required | Further assessment | 0.47 (not a verdict) | 3 |

The Online Store and Food Delivery results show the proposed design costing about the same or
slightly more in the model, and the release documents this rather than presenting only favourable
cases.

## 6. How to run and how to demonstrate

- **Run:** see the README. macOS/Linux: create `.venv`, install `backend/requirements.txt`,
  `uvicorn app.main:app` from `backend/` on port 8000, then `npm ci && npm run dev` in `frontend/`
  and open http://localhost:5173. Single-process: `npm run build`, then start uvicorn with
  `NYX_STATIC_DIR=../frontend/dist` and open http://localhost:8000.
- **Demonstrate:** follow `docs/DEMO_GUIDE.md`. Key moments: the Online Examination verdict and
  its factor table; the Current and Proposed diagrams with the provider switch; the honest cost
  disclaimer; the provisional Document Processing Pipeline; save, reopen and export.

## 7. Limitations

- **Visual quality is unverified in a browser.** No browser was available. Layout was checked by
  build output, class-name validation (Tailwind rejects invalid opacity steps; these were fixed) and
  tests, not by looking at the screens.
- **Windows PowerShell** commands are standard but were not executed on Windows. No PowerShell
  helper script is shipped, because none could be tested here.
- **Scores are heuristics** over the description. Their value depends on how specific the input
  is; the provisional verdict makes gaps visible but cannot remove them.
- **Cost is relative** (RICU). It does not include real prices, discounts, data transfer tiers,
  reserved capacity or currency. The catalogue is a curated list of services and links, not a price
  list, and it was not checked against live provider documentation in this release.
- **Security review is architectural.** It is not a penetration test or a compliance certification.
- **Single-user local storage.** SQLite, no authentication, no multi-tenancy. The API is intended for
  a trusted local network, not the public internet.
- **AI assist** was exercised with the rules engine only (AI off) and with stub providers in tests.
  No live AI endpoint was tested.
- **No provisioning.** NYX never calls a cloud provider.
- **Independent review** has not been performed.

## 8. Files changed

Recorded from `git status` at the time of writing (this branch, relative to `e0ada1d`).

**Modified:**
`.env.example`, `.gitignore`, `README.md`, `backend/app/api/routes/meta.py`, `backend/app/main.py`,
`backend/app/rules/suitability_rules.py`, `backend/app/services/cloud_catalog.py`,
`backend/app/services/report_generator.py`, `backend/app/services/security_analyzer.py`,
`backend/app/services/serverless_suitability.py`, `backend/app/services/templates.py`,
`backend/scripts/export_typescript_schema.py`, `backend/tests/test_api_meta.py`,
`backend/tests/test_reports.py`, `backend/tests/test_suitability.py`, `frontend/package.json`,
`frontend/package-lock.json`, `frontend/src/App.tsx`, `frontend/src/index.css`,
`frontend/src/lib/api.ts`, `frontend/src/lib/tone.ts`, `frontend/src/main.tsx`,
`frontend/src/types/analysis.ts` (regenerated), `frontend/src/types/nyx.ts`,
`frontend/tailwind.config.js`, `frontend/vite.config.ts`.

**Added:**
`backend/app/data/cloud_services.json`, `backend/app/data/templates.json`,
`backend/tests/test_data_integrity.py`, `backend/tests/test_static_hosting.py`,
`backend/tests/test_suitability_regression.py`, `docs/METHODOLOGY.md`, `docs/DEMO_GUIDE.md`,
`docs/audits/NYX_V1_IMPLEMENTATION_AUDIT.md`, `frontend/eslint.config.js`,
`frontend/tailwind.config.d.ts`, `frontend/src/app.test.tsx`, `frontend/src/design-system.test.ts`,
`frontend/src/lib/api.test.ts`, `frontend/src/types/nyx.test.ts`, `frontend/src/components/`
(`ui.tsx`, `Layout.tsx`, `ArchitectureDiagram.tsx`, `ArchitectureDiagram.test.tsx`),
`frontend/src/results/` (Overview, Architecture, Services, Cost, Security, Migration and Results
views), `frontend/src/pages/` (Home, Analyze, Results, Projects, Project, Method, NotFound),
`frontend/src/test/` (`setup.ts`, `harness.tsx`, `fixtures/meta.json`,
`fixtures/sample-analysis.json`).

**Not committed (ignored):** `frontend/node_modules/`, `frontend/dist/`, `__pycache__/`, `.venv/`,
`backend/data/`, SQLite files.

**Repository safety:** no history rewritten, no force push, no pull request merged or closed, no
destructive cleanup. Work is on `arena/1435d4fc-nyx` only.

## 9. Git status

Branch `arena/1435d4fc-nyx`, based on `e0ada1d`. The release commit and its push are recorded in the
final message of the session, because this document cannot contain the hash of the commit that
contains it.
