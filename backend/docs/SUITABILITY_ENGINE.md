# NYX Serverless Suitability Engine

**Authoritative module:** `backend/app/services/serverless_suitability.py`
**Authoritative rule pack:** `backend/app/rules/suitability_rules.py`
**Rule pack version:** `2026.10` (`RULE_PACK_VERSION`)
**Status:** implemented and covered by `backend/tests/test_suitability_engine.py`

This document describes the engine **as it is implemented**. Every rule below is
executed by the code paths named alongside it; the pinned behaviour is verified by
the test suite rather than asserted from memory.

---

## 1. Where the engine lives, and why only there

Two modules own suitability, with a strict separation:

| Module | Owns | Imports |
|---|---|---|
| `app/rules/suitability_rules.py` | The *rules*: factor tables, weights, band thresholds, evidence gates, rule-pack version | `app.schemas.*` only |
| `app/services/serverless_suitability.py` | The *composition*: rules → `SuitabilityReport` | rule pack, `app.schemas.*`, `app.services.component_identifier` |

The rule pack is pure: no I/O, no network, no model call, no mutable state. The
service is the **only** module in the repository that composes a suitability
verdict. Nothing else computes, re-weights, re-bands or overrides a score.

### Entry points

```python
from app.services.serverless_suitability import evaluate_suitability

report = evaluate_suitability(requirements, signals, plans)
```

| Name | Role |
|---|---|
| `evaluate_suitability(requirements, signals, plans)` | **Authoritative entry point.** Validates inputs, evaluates workload and components once each, blends, applies the evidence gate, returns a `SuitabilityReport`. |
| `SuitabilityService().assess(...)` | Stateless instance wrapper. Delegates to `evaluate_suitability`; contains no logic of its own. Retained because the analysis pipeline holds a service instance per stage. |
| `report_from_service(...)` | Backwards-compatible alias. Delegates to `evaluate_suitability`. |

All three are proven equivalent by
`test_there_is_one_authoritative_engine_and_one_rule_pack_version`.

### Call sites

| Location | Call |
|---|---|
| `app/services/pipeline.py` (`AnalysisPipeline`) | `evaluate_suitability(requirements, signals, plans)` — the only production call site |
| `app/api/routes/meta.py` | Publishes `BANDS`, `WEIGHT_RATIONALE` and `RULE_PACK_VERSION`, imported from the rule pack |
| `architecture_engine.py`, `migration_planner.py`, `report_generator.py`, `project_store.py` | Consume `SuitabilityReport`; they do not score |

---

## 2. Scoring methodology

### 2.1 Factor scoring

Each factor produces an **impact** in `[-1, +1]` from the rule tables, plus a
**basis** recording where that impact came from:

| `basis` | Meaning |
|---|---|
| `user_provided` | The user stated it explicitly |
| `inferred` | Derived from stated facts |
| `default` | Neutral default applied and disclosed as an assumption |
| `missing` | No evidence at all |

```
contribution_i = weight_i x impact_i
score          = round(clamp(100 x (0.5 + 0.5 x Σ contribution_i), 0, 100), 1)
missing_weight = Σ weight_i  for factors whose basis == "missing"
```

Implemented by `score_from_factors` in the rule pack. A perfect workload scores
100, a perfectly unsuitable one 0, and a completely unknown one 50 — but the
unknown case is gated before it is ever published as a verdict (section 2.4).

**A missing factor always contributes exactly 0.** It is never defaulted to a
favourable value, and it is always listed in `missing_inputs`.

### 2.2 Workload factors (12, weights sum to 1.00)

| Factor id | Name | Weight |
|---|---|---|
| `traffic_variability` | Traffic variability | 0.16 |
| `execution_duration` | Execution duration | 0.14 |
| `event_driven_nature` | Event-driven work | 0.12 |
| `request_response_shape` | Request/response shape | 0.10 |
| `statelessness` | Stateless execution | 0.10 |
| `persistent_connections` | Persistent connections | 0.08 |
| `database_connection_pattern` | Database connection pattern | 0.07 |
| `resource_intensity` | Resource intensity | 0.06 |
| `storage_fit` | Storage fit | 0.05 |
| `availability_requirement` | Availability requirement | 0.05 |
| `cold_start_sensitivity` | Cold-start sensitivity | 0.04 |
| `runtime_constraints` | Runtime constraints | 0.03 |

Ordering rationale (`WEIGHT_RATIONALE`, published in every report): execution
duration and traffic variability first, then coupling (state, persistent
connections, database connection patterns), then resource and runtime
constraints. **These are engineering judgement for this rule-pack version, not an
industry benchmark.** No weight is randomly generated and none is model-generated.

### 2.3 Component scoring and the blend

Components are scored only when their architectural tier represents a genuine
compute decision:

```python
SCORED_TIERS = {ComponentTier.APPLICATION, ComponentTier.PROCESSING}
```

Queues, streams, notification channels, identity, data stores and observability
components are **excluded on purpose** — their realization is a managed service
by definition, and scoring them as function candidates would be misleading.

Component factors and weights:

| Factor | Weight |
|---|---|
| `trigger` | 0.28 |
| `duration` | 0.26 |
| `state` | 0.18 |
| `connections` | 0.12 |
| `runtime` | 0.10 |
| `fixed_overhead` | 0.06 |

The blended score (`aggregate_score`):

```
overall = round(0.55 x workload_score + 0.45 x mean(component_scores), 1)
```

If no component is scoreable, `overall = workload_score`. Each component is
evaluated **exactly once**; the missing weight used for the evidence gate is
taken from those same factor results, so score and evidence quality can never
disagree.

### 2.4 Evidence-quality gate

```python
MISSING_WEIGHT_LIMIT = 0.30
```

When missing evidence reaches 30% of deciding weight, `overall_outcome` overrides
the band:

- `outcome` becomes `further_assessment_required`
- `provisional = True`
- the blended number is published as **`provisional_score`**, and `score` falls
  back to the workload-only score
- a caveat stating the missing percentage is prepended to `caveats`
- `recommended_pattern` becomes `further_assessment`

This is what stops a one-line description from producing a confident number.

### 2.5 Bands

`BANDS` in the rule pack is the only place thresholds are defined:

| Threshold | Outcome | Meaning |
|---|---|---|
| ≥ 78.0 | `strong_candidate` | Fits a managed function platform with little architectural compromise |
| ≥ 62.0 | `suitable_with_modifications` | Suitable once specific coupling or duration issues are restructured |
| ≥ 45.0 | `partial_serverless_adoption` | Adopt serverless for the event-driven and spiky pieces; keep the rest on containers or managed services |
| ≥ 0.0 | `poor_candidate_for_proposed_serverless` | Stated constraints conflict with short-lived per-invocation execution |

Ordering note: the rule pack stores `BANDS` **descending** (so `band_for` can
pick the first match). `methodology.bands` republishes the same thresholds
**ascending**, because it reads as a ladder from the floor upward.
`GET /api/meta` publishes the rule pack's own descending order. Thresholds are
never restated — only reordered.

### 2.6 Recommended pattern

`recommended_pattern` can return any of six values, and it is not biased toward
serverless:

| Condition | Pattern |
|---|---|
| Evidence gate fired | `further_assessment` |
| `strong_candidate` and at least one component targets a function | `serverless_first` |
| `suitable_with_modifications`, some component is neither function nor managed service | `hybrid` |
| `suitable_with_modifications`, all components are function or managed service | `serverless_where_suitable` |
| `partial_serverless_adoption` | `hybrid` |
| `resource_intensity` or `execution_duration` impact ≤ −0.65 | `managed_container` |
| otherwise | `conventional_keep` |

**`hybrid` is reachable** and is verified by
`test_a_hybrid_recommendation_is_reachable_and_component_aware`, which requires a
single workload to receive both `serverless_function` and `container`
recommendations at component level. Equally, `test_an_unsuitable_workload_is_not_labelled_serverless_friendly`
pins that a long-running, stateful, GPU-bound, warm-pool workload is **not**
labelled `serverless_first`.

---

## 3. Determinism

The engine is deterministic by construction:

- no randomness, no clock, no UUID, no environment read in the scoring path
- no model call and no network call — the suitability path never imports
  `ai_provider`, `cloud_catalog`, `httpx` or any route
- no mutable module- or instance-level state that survives a call;
  `SuitabilityService` carries no per-call state, so a shared instance is safe
  across threads and repeated calls
- inputs are never mutated
- `plans` is materialised once at the start of the call, so a list, tuple or
  generator all produce the same report

`test_equivalent_normalized_inputs_produce_identical_reports` asserts byte-equal
`model_dump(mode="json")` across 50 consecutive calls, across two independently
constructed but equivalent requests, and across iterable forms.

### Input validation

`evaluate_suitability` rejects malformed arguments with `TypeError` rather than
coercing them into a score: non-`ApplicationRequirements`, non-`RequirementSignals`,
a non-iterable `plans`, a string/bytes `plans`, or a `plans` element that is not a
`ComponentPlan`. Covered by `test_malformed_input_is_rejected_rather_than_scored`.

---

## 4. What every report contains

`SuitabilityReport` fields: `score`, `provisional_score`, `outcome`, `headline`,
`rationale`, `recommended_pattern`, `factors[]`, `supporting_evidence[]`,
`concerns[]`, `components[]`, `methodology`, `missing_inputs[]`, `caveats[]`.

Each `SuitabilityFactor` carries `id`, `name`, `weight`, `impact`,
`contribution`, `evidence[]`, `explanation`, `direction`, `basis` — so any score
can be recomputed from the published payload alone.

`methodology` carries `formula`, `band_source` (naming the rule-pack version),
`weight_source` (`WEIGHT_RATIONALE`), `bands[]` and `notes[]` including the
evidence-gate percentage. Two standing caveats are always present: scores are
heuristic estimates, not an industry benchmark; and provider quotas, regional
availability and service limits must be re-verified before implementation.

---

## 5. Known limitations and residual duplication

These are recorded, not hidden. Each one is a deliberate decision.

### 5.1 The component-level evidence gate is dormant

`COMPONENT_MISSING_WEIGHT_LIMIT = 0.34` gates `component_score_and_outcome`.
**It can never fire.** `duration` (weight 0.26) is the only component factor that
can ever be reported `missing`; the maximum achievable component missing weight is
therefore 0.26 < 0.34. A component verdict is always taken from `band_for`.

The value is preserved verbatim from the pre-consolidation implementation.
Lowering it to something reachable would change published component outcomes,
`ComponentSuitability.provisional`, and — through the component targets —
`recommended_pattern`. **That is a behaviour change requiring an explicit
project-owner decision, not a refactor**, so it was named and documented instead
of being silently altered.

`test_evidence_gates_keep_their_documented_values_and_the_component_gate_is_known_to_be_dormant`
sweeps the full trait space exhaustively (240 evaluations across every
`ComponentTraits` enum combination × both penalty states × three spike factors)
and proves the claim rather than asserting it.

### 5.2 The frontend restates the band thresholds

`frontend/src/lib/tone.ts` (`scoreTone`) hardcodes `78` / `62` / `45` while its
own comment says it uses "the same bands the backend publishes in `/api/meta`".
It does not read them. If `BANDS` ever changes, the UI colour bands will silently
diverge from the backend verdict.

**Not fixed here** — NYX-BE-014 is explicitly forbidden from modifying frontend
source. Recommended follow-up: have the UI read the bands from the `/api/meta`
payload it already fetches. **Flagged for the NYX Project Auditor.**

### 5.3 `rule_pack_version` has a schema-level default

`app/schemas/analysis.py` declares `rule_pack_version: str = "2026.10"`. This is
the one remaining restatement of the rule-pack version.

**Not fixed here — and it cannot be fixed by importing the constant**, because
`app/rules/suitability_rules.py` imports `app.schemas.*`. Having the schemas
import the rule pack would create a circular dependency, which this task
explicitly forbids. In practice the pipeline always overwrites the default with
the imported `RULE_PACK_VERSION`, so the default is only reachable for an
`AnalysisResult` constructed without going through the pipeline.
`test_there_is_one_authoritative_engine_and_one_rule_pack_version` enforces that
no module other than the rule pack **assigns** `RULE_PACK_VERSION`.

(`app/schemas/architecture.py`'s `version: str = "2026.10"` is the *catalogue*
version — a different concept, owned by the cloud catalogue, and out of scope.)

### 5.4 Six suitability tests cannot run in this environment

`backend/tests/test_suitability.py` contains 19 tests. **13 pass; 6 fail** with
`FileNotFoundError: app/data/templates.json`. That file — like
`app/data/cloud_services.json` — is absent from the repository and excluded by the
bare `data/` rule in `.gitignore`, so it was never committed.

This is a **pre-existing data-asset problem, not a suitability defect**. The
suitability path itself is dependency-free (no catalogue, no templates), which is
why the other 13 tests and the entire new `test_suitability_engine.py` suite run
without those assets. Fixing it requires the project owner to supply the real
template and catalogue data; fabricating them would make the tests pass while
testing nothing.

### 5.5 Scores are heuristic, not a benchmark

Weights are engineering judgement fixed per rule-pack version. They are not
derived from an industry standard, and a score is not a guarantee that a
migration will succeed. Both statements are published in every report's
`caveats`.

---

## 6. How to verify

```bash
cd backend
python -m pytest tests/test_suitability_engine.py -q   # 21 passed
python -m pytest tests/test_suitability.py -q          # 13 passed, 6 failed (missing app/data/templates.json)
```

The 13-case contract suite is `backend/tests/test_suitability_engine.py`. It has
no dependency on the cloud catalogue or the template library, and every
expectation in it is a literal — nothing is time- or random-dependent.

### Verification record

Commands actually executed against this change, with the results they returned:

| Check | Command | Result |
|---|---|---|
| New contract suite | `pytest tests/test_suitability_engine.py -q` | **21 passed, 0 failed** (13 test functions, 5 of them parametrised) |
| Pre-existing suitability suite | `pytest tests/test_suitability.py -q` | **13 passed, 6 failed** — identical to the pre-change baseline; all 6 fail on `FileNotFoundError: app/data/templates.json` |
| Behavioural equivalence | 10-scenario golden snapshot (full `model_dump(mode="json")` per scenario, incl. a per-scenario SHA-256), captured before the refactor and re-captured after | **byte-identical** |
| No new failures anywhere | full backend suite, run with `backend/app/` stashed and again with the change applied, same command both times | **124 failing test names before, the same 124 after — no new failures, none fixed** |
| Lint | `ruff check` over the four touched modules plus the new test file, using the repo's own `[tool.ruff]` config | **13 errors after vs 15 before** — every remaining error pre-existed; the change removed one (`RUF059`, an unused unpacked variable) and added none |
| Import hygiene | import of every module under `app/` | **no module fails to import; no circular dependency** |

Note on the full-suite figure: the backend suite cannot pass in this environment
at all, because `app/data/cloud_services.json` and `app/data/templates.json` are
absent from the repository (excluded by the bare `data/` rule in `.gitignore`).
`tests/test_cloud_mapping.py` fails at *collection* time for that reason and had
to be excluded for the run to proceed. The before/after comparison above is
therefore the meaningful signal: identical failure sets. This is pre-existing
finding F-01 from the repository audit, unrelated to suitability.
