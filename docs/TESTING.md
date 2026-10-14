# NYX testing

Every command below is run from the repository root unless it says otherwise. On Windows
PowerShell, use `.\.venv\Scripts\python.exe` in place of `.venv/bin/python`, and the same
`npm` commands. The PowerShell forms have not been run on a Windows machine by the project
team; they are the standard equivalents.

## What each check proves

| Check | Command | What it proves | Needs |
| --- | --- | --- | --- |
| Backend unit, contract and workflow tests | `cd backend && ../.venv/bin/python -m pytest -q` | The rules, schemas, API contract, persistence, exports and data files behave as specified. | Python venv with `backend/requirements.txt` |
| Frontend typecheck | `cd frontend && npm run typecheck` | The TypeScript client matches the generated contract. | `npm ci` |
| Frontend lint | `npm run lint` | The client source passes ESLint with no warnings allowed. | `npm ci` |
| Frontend unit and workflow tests | `npm test` | Components, client error handling, validation messages, the design rules and the results workflow. | `npm ci` |
| Production build | `npm run build` | The client compiles and bundles. | `npm ci` |
| Live API smoke test | `python scripts/api_smoke.py` | A running backend answers the documented endpoints, validation, exports, the project lifecycle and the error envelope, and the five samples return the documented scores. | Backend running on port 8000; standard library only |
| Browser walkthrough | `python scripts/browser_journey.py` | The real interface completes the main journey in Chromium: sample, form, analysis, results, architecture inspection, save, reopen, export and validation. | Backend on 8000, web client on 5173, Playwright (development only) |

## Backend

```bash
cd backend
../.venv/bin/python -m pytest -q
```

The suite uses temporary fixtures and does not touch your saved projects. Test modules are
grouped by concern:

- `test_suitability_engine.py`, `test_suitability_regression.py`, `test_suitability.py`: the
  scoring engine, its bands, the missing-input behaviour and the regression pins across every
  trait combination.
- `test_requirements.py`, `test_architecture.py`, `test_cloud_mapping.py`, `test_cost.py`,
  `test_security.py`, `test_migration.py`: each stage of the pipeline.
- `test_analysis_api.py`, `test_api_meta.py`, `test_projects.py`, `test_static_hosting.py`: the
  HTTP contract, the error envelope (including malformed JSON), projects and static serving.
- `test_reports.py`, `test_report_labels.py`: Markdown and JSON reports, readable labels in
  prose, and the single export filename rule.
- `test_ai_provider.py`: the optional AI path, including disabled and failing providers.
- `test_data_integrity.py`, `test_edge_cases.py`: the catalogue and template files and unusual input.

Last recorded result: **310 passed**, exit 0.

## Frontend

```bash
cd frontend
npm ci
npm run typecheck
npm run lint
npm test
npm run build
```

Test files:

- `app.test.tsx`: the workflow in the jsdom harness: sample to verdict, field-level validation, the
  backend-down message during a run, keyboard navigation, zoom, fit and reset, cost sensitivity rows,
  save, export of saved and unsaved results, reopen, delete confirmation, and the empty state.
- `components/ArchitectureDiagram.test.tsx`: layout, edge routing, label wrapping and clipping, and
  accessible node controls that report selection.
- Keyboard use of the diagram (Tab between components, Enter to select) is exercised in `app.test.tsx`.
- `lib/api.test.ts`: the typed client. Covers the error envelope, unreachable backends (network
  failure, gateway status, and the dev proxy's 500 with or without its message), timeouts and
  validation details.
- `design-system.test.ts`: the palette is exact, there are no gradients and no green or lime accents
  in client source, and reduced-motion and reduced-transparency rules exist.
- `validation.test.ts`, `types/nyx.test.ts`: input rules and view-model helpers.

Last recorded results: `tsc --noEmit` exit 0; `npm run lint` exit 0; **62 tests passed in 6 files**;
`npm run build` exit 0.

## Live API smoke test

Start the backend (`cd backend` then
`../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`) and run:

```bash
python scripts/api_smoke.py                     # default http://127.0.0.1:8000
python scripts/api_smoke.py --base http://127.0.0.1:8000
```

PowerShell: `.\.venv\Scripts\python.exe scripts\api_smoke.py`

It makes real HTTP requests and checks 25 things, including the documented scores of the five
samples (see [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md#expected-sample-results)). It creates one
temporary project and deletes it before exiting. Exit status 0 means every check passed.

Last recorded result: **25 of 25 checks passed**, exit 0.

## Browser walkthrough

Playwright is a development-only dependency. The application does not need it.

```bash
python -m pip install playwright
python -m playwright install chromium   # or point NYX_CHROMIUM_PATH at an existing Chromium
python scripts/browser_journey.py --base http://localhost:5173 --out browser-evidence
```

Environment: `NYX_CHROMIUM_PATH` (optional) names an existing Chromium binary. Both servers must be
running. The script writes screenshots and `summary.json` to `--out` and exits 0 only when every step
passes. It uses a 1440×900 viewport. It saves one project and leaves it in the Projects list, named
for the walkthrough, so you can delete it from the Projects page afterwards.

Last recorded result: **23 of 23 steps passed**, exit 0, with no uncaught page errors and no console
errors.

### Checks made by hand (not automated)

These were checked in the sandbox with ad-hoc Playwright runs and screenshots. They are not in the
script yet:

- A 390px-wide mobile viewport on results, architecture and projects: the document does not scroll
  sideways; the wide architecture diagram scrolls inside its own region, by design.
- Projects page with the backend stopped: shows “NYX cannot reach its API”, not a generic 500 message.
- Architecture labels at the default zoom, Online Examination sample, at 1440px and 390px: no node label is cut
  with an ellipsis. The other four samples were not inspected this way.

## What is not tested

- AI-assisted extraction against a real OpenAI-compatible endpoint (no endpoint is configured in the
  sandbox). The disabled and failing provider paths are tested.
- Windows PowerShell commands (documented, not executed on Windows).
- Browsers other than Chromium, and real mobile devices.
- Keyboard focus order beyond Tab and Enter on a diagram node.
- Accessibility by an audit tool or screen reader. The checks above are by inspection and unit tests.
