# NYX methodology

This document describes how NYX reaches its results. Every number below is taken
from the rule pack in `backend/app/rules/` (rule pack **2026.10**); if the code and
this page ever disagree, the code wins and this page should be corrected.

NYX is a **rules engine**. Given the same input it returns the same output. The
optional AI assist can only propose values for requirement fields; it cannot change
scores, mappings, costs, findings or the plan (see “AI assist” below).

## 1. From description to signals

Free text is read by `requirement_extractor` and `rules/requirement_rules.py`
(keyword rules with recorded provenance). Each signal records where it came from:

| Basis | Meaning |
| --- | --- |
| `user_provided` | You stated it on the form or in the description. |
| `template` | It came from a sample template you chose. |
| `inferred` | Read from the wording of the description. |
| `default` | A documented default was used (the UI says so). |
| `missing` | Nothing supports it. It is listed as missing and never counted as favourable. |

## 2. Workload suitability score

The workload is scored on twelve weighted factors. Weights sum to 1.00.

| Factor | Weight |
| --- | --- |
| Traffic variability | 0.16 |
| Execution duration | 0.14 |
| Event-driven work | 0.12 |
| Request/response shape | 0.10 |
| Stateless execution | 0.10 |
| Persistent connections | 0.08 |
| Database connection pattern | 0.07 |
| Resource intensity | 0.06 |
| Storage fit | 0.05 |
| Availability requirement | 0.05 |
| Cold-start sensitivity | 0.04 |
| Runtime constraints | 0.03 |

Each factor produces an impact between −1 and +1. The score is
`100 × (0.5 + 0.5 × Σ weight × impact)`, clamped to 0–100. The weight rationale is
published by `/api/meta` (`suitability.weight_rationale`).

Verdict bands (`suitability_rules.BANDS`):

| Score from | Verdict |
| --- | --- |
| 78 | Strong candidate |
| 62 | Suitable with modifications |
| 45 | Partial serverless adoption |
| 0 | Poor candidate for proposed serverless |

### Provisional verdicts

If the workload weight without evidence reaches **0.30** (`MISSING_WEIGHT_LIMIT`),
NYX still shows the score, but as a *provisional* score, and it withholds the
outcome (“further assessment required”). Gaps are listed under “Missing inputs”.
Missing evidence is never silently treated as favourable.

## 3. Component suitability

Each logical component is scored on six factors: trigger (0.28), duration (0.26),
state (0.18), connections (0.12), runtime (0.10) and fixed overhead (0.06). The
component verdict is always the score band.

Only `duration` can lack evidence at component level, so the largest missing weight
a component can carry is 0.26. An earlier revision also overrode a component to
“further assessment” at 0.34. That branch could never fire and was removed. Component
gaps remain visible in `missing_inputs`. `backend/tests/test_suitability_regression.py`
pins this decision across every trait combination.

## 4. Recommended pattern

Applied in this order (`recommended_pattern` in `suitability_rules.py`):

1. Further assessment required → **Further assessment**.
2. Strong candidate and at least one serverless component → **Serverless first**.
3. Suitable with modifications → **Hybrid** if any component stays on a non-serverless target, otherwise **Serverless where suitable**.
4. Partial adoption → **Hybrid**.
5. Otherwise: **Managed container** if the work is long-running or resource-heavy, else **Conventional, keep**.

## 5. Cloud service mapping

Logical components (for example “application logic”, “primary store”, “object
storage”) map to AWS, Google Cloud and Azure services from
`backend/app/data/cloud_services.json` (catalogue **2026.10**, 81 services).

The catalogue lists services, their serverless class (`fully_serverless`, `managed`,
`serverful`), links and limitations. **It is not a pricing file and carries no prices.**
Each mapping carries a confidence grade (high, medium or low) and, where the
equivalence is imperfect, the differences.

## 6. Cost model (relative units)

Costs are computed in **RICU** (Relative Infrastructure Cost Unit): 1 RICU is the
relative monthly cost of one small always-on compute unit (1 vCPU / 2 GB class). The
model compares a conventional, always-provisioned design with the proposed design
for the same traffic. It reports fixed, variable and operational shares, and a
sensitivity table for traffic changes.

No currency is implied and no provider price is used. The rate table is shown in
the result and in `/api/meta`. Use the figures to compare shapes of cost, not to
budget.

## 7. Security review (architecture level)

The review applies rules to the modelled architecture and reports findings with a
severity and a certainty:

- **Confirmed in the model**: the design states it directly.
- **Inferred risk**: follows from what is stated, but needs confirmation.
- **Needs verification**: the model cannot answer it; a suggested check is given.

Rule identifiers: SEC-TLS, SEC-AT-REST, SEC-NO-AUTH, SEC-IAM-BROAD,
SEC-IAM-UNSPEC, SEC-SECRETS, SEC-INPUT-VAL, SEC-BOUNDARY, SEC-EDGE-TO-DATA,
SEC-PUBLIC-STORE, SEC-AUDIT, SEC-CLASSIFY, SEC-BACKUP-UNSPEC, SEC-NO-BACKUP,
SEC-CONCURRENCY, SEC-COLDSTART, SEC-TENANT.

This is a design review. It is not a penetration test and not a compliance
certification.

## 8. Migration plan

The plan is generated from the component changes and the complexity drivers. Phases
are generated only when the analysis calls for them, and each has objectives,
activities, exit criteria, risk and effort. The phase titles used by the rules are:

1. Inventory and preparation
2. Configuration and storage changes
3. Storage and artefact changes
4. Data migration and reconciliation
5. Identity and access cutover
6. Component decomposition
7. Observability, backup and recovery
8. Testing and validation
9. Deployment preparation

Complexity is scored from the drivers listed in the result (state, duration,
connections, runtime, data volume and dependencies).

## 9. AI assist (optional)

AI is off unless an OpenAI-compatible endpoint is configured. Even when it is on:

- The model may only propose values for requirement fields.
- Every proposal is validated against the schema; rejected fields are reported.
- Scoring, mapping, cost, security and migration remain rule-based.
- Results that used AI are labelled as such. Their exports come from the saved copy.

## 10. Reproducibility

Identical requirements with AI off produce identical results (apart from the
analysis identifier and timestamp). The test suite checks this and pins
representative scores.
