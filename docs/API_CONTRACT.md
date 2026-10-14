# NYX API contract

The backend is authoritative. The request and result schemas are `nyx.analysis/1`, defined
in `backend/app/schemas/` and exported to OpenAPI. The live, interactive description is at
**http://localhost:8000/api/docs** (and the raw document at `/api/openapi.json`) while the
API runs. The web client talks to it only through relative `/api/...` paths.

## Conventions

- Base path: `/api`. All request and response bodies are JSON unless noted.
- Analysis is deterministic. The same input and the same rule pack produce the same result,
  apart from `analysis_id`, `created_at` and `duration_ms`.
- The frontend does not compute scores or business rules. It renders what the API returns.

### Error envelope

Every error uses one shape:

```json
{ "error": { "code": "INVALID_REQUEST", "message": "…", "details": ["requirements.description: …"], "retryable": false } }
```

| HTTP status | `code` | When |
| --- | --- | --- |
| 422 | `INVALID_REQUEST` | The body does not satisfy the schema. `details` lists up to 8 field-scoped messages, for example `requirements.name: Field required (missing)`. |
| 422 | `INVALID_REQUEST` (with `json_invalid`) | The body is not valid JSON. `details` says `body: the request body is not valid JSON.` |
| 404 | `PROJECT_NOT_FOUND` | No saved project has that id. |
| 404 | `HTTP_404` | Any other unknown path, for example `/api/does-not-exist`. |
| 500 | `INTERNAL_ERROR` | An unexpected failure. The message is generic; no stack trace or secret is returned. |
| other | `HTTP_<status>` | Other HTTP errors raised by the framework. |

`retryable` is `true` only where retrying can help (server-side failures). Validation
failures are never retryable.

The web client maps a non-JSON 5xx or a dev-proxy failure (backend not running) to
`api_unreachable`, shown as “NYX cannot reach its API”.

### Input limits

Limits come from the schema, not from the UI. `GET /api/meta` returns them under `limits`:

| Field | Limit |
| --- | --- |
| `name` | 2 to 90 characters |
| `description` | 10 to 4,000 characters |
| `additional_requirements` | up to 2,000 characters |
| `expected_users` | 1 to 500,000,000 (when given) |
| `max_operations_per_view` | between 6 and 24 (default 14) |

## Endpoints

| Method and path | Purpose | Status codes |
| --- | --- | --- |
| `GET /api/health` | Liveness, versions, engine mode, AI and storage status. Never returns a secret. | 200 |
| `GET /api/meta` | Enumerations, the five sample templates, scoring bands and weights, cost rates, catalogue summary, input limits. | 200 |
| `GET /api/ai/status` | Whether an OpenAI-compatible endpoint is configured. Shows `not_configured` with a message when it is not. Never shows the key. | 200 |
| `POST /api/analyze` | Run the analysis and return the full `AnalysisResult`. Nothing is stored. | 200, 422 |
| `POST /api/analyze/export` | Run the analysis and return an export envelope for `markdown` or `json`. Nothing is stored. | 200, 422 |
| `GET /api/projects` | List saved projects. Query: `limit` (1–200, default 50), `offset` (0–10,000), `kind` (`user_project` or `example_project`). | 200, 422 |
| `POST /api/projects` | Create a project: runs the analysis and stores the full result. Body: `requirements` (required); optional `name`, `options`, `result`, `client_id`. | 201, 422 |
| `GET /api/projects/stats` | Counts derived from stored rows (total, user, example, outcomes, application types). | 200 |
| `GET /api/projects/{id}` | Reopen a project: summary, requirements and full result. | 200, 404 |
| `PUT /api/projects/{id}` | Rename (`name`), edit `notes` (up to 2,000 characters), or change `requirements` and re-run with `reanalyze: true`. | 200, 404, 422 |
| `DELETE /api/projects/{id}` | Delete a project. Returns `{"deleted": true, "id": …}`. | 200, 404 |
| `GET /api/projects/{id}/export.json` | JSON export envelope. | 200, 404 |
| `GET /api/projects/{id}/report.md` | Markdown report as a file download (`text/markdown`). | 200, 404 |
| `GET /api/projects/{id}/graph?view=&provider=` | One architecture view projected for a provider. `view` is `conventional` or `proposed`; `provider` is `aws`, `gcp` or `azure`. | 200 (422 for a bad query) |

Some of these return an envelope rather than raw text:

### Export envelope

`POST /api/analyze/export` and `GET /api/projects/{id}/export.json` return

```json
{ "format": "markdown", "filename": "nyx-report-online-examination-platform.md", "content": "…" }
```

Parse `content`; do not assert on the raw body. The frontend saves the file using `filename`.

### File names

All exports use one rule, `nyx-report-<slug of the analysis title>.<md|json>`, whether the
result is saved or not. The slug is limited to 48 characters. The same name appears in the
`Content-Disposition` header of the saved-project downloads.

### Analysis request

`POST /api/analyze` takes `{ "requirements": {…}, "options": {…} }`. `requirements` follows the
`ApplicationRequirements` input schema (name, description, and the optional structured fields
listed in `GET /api/meta`). `options.use_ai` defaults to `true` in the schema, and
`options.providers`, `default_provider` and `max_operations_per_view` (6–24, default 14) shape the
output. The web client sends `use_ai` only when `GET /api/meta` reports an AI endpoint as
configured. When no endpoint is configured, the deterministic engine runs and the result says so
(`engine_mode: deterministic_rules`, and a limitation entry carrying the AI status).

### Result shape

The result (`nyx.analysis/1`) contains: `application` (normalised requirements with per-field
provenance), `assumptions`, `open_questions`, `limitations`, `workload`, `component_inventory`,
`architectures` (conventional and proposed graphs with positions), `suitability` (score,
outcome, recommended pattern, factors, missing inputs, components), `cost` (RICU comparison,
sensitivity, scenarios, rate table), `security` (findings and verification gaps),
`migration` (phases and per-component changes), `ai` (attempt status), `engine_mode`, and the
version fields `schema_version`, `rule_pack_version`, `catalog_version`.

The authoritative field list is the OpenAPI document; `frontend/src/types/analysis.ts` is
generated from the backend schemas by `backend/scripts/export_typescript_schema.py`.

## Versioning

- `schema_version`: `nyx.analysis/1`.
- `rule_pack_version`: `2026.10`. Any change to a weight, threshold or rule should be recorded as a new rule-pack version, so that stored results stay traceable.
- `catalog_version`: `2026.10` (81 services in `backend/app/data/cloud_services.json`).
