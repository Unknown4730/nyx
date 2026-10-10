"""NYX serverless suitability rule pack.

Methodology (also documented in docs/PROJECT_REPORT.md):

    contribution_i = weight_i * impact_i                 impact_i in [-1, +1]
    score          = 100 * (0.5 + 0.5 * sum(contribution_i))
    missing_weight = sum(weight_i for factors with no evidence)

A workload perfect on every factor reaches 100; a perfectly unsuitable one
reaches 0; a completely unknown one lands at 50 and is flagged *provisional*
rather than being presented as a verdict.  No score is ever random.

Weights are fixed by this rule pack version so results are reproducible and
unit-testable.  They are engineering judgement, not an industry benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.schemas.architecture import ComponentTraits
from app.schemas.common import (
    AvailabilityExpectation,
    ComponentRuntime,
    DataStorageKind,
    DeploymentTarget,
    DurationProfile,
    FieldBasis,
    RecommendedPattern,
    SuitabilityOutcome,
    TrafficPattern,
)
from app.schemas.requirements import ApplicationRequirements, RequirementSignals

RULE_PACK_VERSION = "2026.10"
MISSING_WEIGHT_LIMIT = 0.30

WEIGHT_RATIONALE = (
    "Weights prioritise the factors with the largest documented impact on serverless platform limits: "
    "execution duration and traffic variability first, then coupling (state, persistent connections, "
    "database connection patterns), then resource/runtime constraints.  They are fixed for this rule "
    "pack version so that scores are reproducible and testable, and they are not an industry standard."
)


@dataclass
class FactorResult:
    """Outcome of evaluating one factor against the extracted evidence."""

    id: str
    name: str
    weight: float
    impact: float
    explanation: str
    evidence: list[str] = field(default_factory=list)
    basis: str = "inferred"  # user_provided | inferred | default | missing
    mitigation: str | None = None

    @property
    def direction(self) -> str:
        if self.impact > 0.15:
            return "positive"
        if self.impact < -0.15:
            return "negative"
        return "neutral"

    @property
    def contribution(self) -> float:
        return round(self.weight * self.impact, 4)


@dataclass
class EvaluationContext:
    """Everything a factor is allowed to look at."""

    requirements: ApplicationRequirements
    signals: RequirementSignals
    spike_factor: float = 1.35  # peak/average, assumed when not derivable
    spike_is_assumed: bool = True

    @property
    def storage_kinds(self) -> set[str]:
        return {kind.value for kind in self.requirements.data_storage}

    def basis_of(self, name: str) -> str:
        """Map a FieldBasis onto the factor `basis` vocabulary.

        Signals record a bare `FieldBasis`; requirements record a
        `FieldProvenance`, so both shapes have to be unwrapped here or a value
        the user typed would be labelled as inferred.
        """
        origin = self.signals.provenance.get(name)
        if origin is None:
            origin = getattr(self.requirements.provenance.get(name), "basis", None)
        if origin in (FieldBasis.USER, FieldBasis.TEMPLATE):
            return "user_provided"
        if origin in (FieldBasis.INFERRED, FieldBasis.AI):
            return "inferred"
        if origin == FieldBasis.DEFAULT:
            return "default"
        return "missing"


def _factor_result(
    factor: "WeightedFactor",
    ctx: EvaluationContext,
    impact: float,
    explanation: str,
    evidence: list[str],
    basis_name: str,
    fallback_basis: str = "inferred",
    mitigation: str | None = None,
) -> FactorResult:
    basis = ctx.basis_of(basis_name) if basis_name else fallback_basis
    if basis == "missing":
        basis = fallback_basis
    return FactorResult(
        id=factor.id,
        name=factor.name,
        weight=factor.weight,
        impact=round(max(-1.0, min(1.0, impact)), 3),
        explanation=explanation,
        evidence=evidence,
        basis=basis,
        mitigation=mitigation,
    )


def _missing(factor: "WeightedFactor", explanation: str) -> FactorResult:
    return FactorResult(
        id=factor.id,
        name=factor.name,
        weight=factor.weight,
        impact=0.0,
        explanation=explanation,
        evidence=["No supporting statement in the inputs."],
        basis="missing",
    )


@dataclass
class WeightedFactor:
    id: str
    name: str
    weight: float
    evaluate: "Callable[[EvaluationContext], FactorResult]"
    question: str = ""


# ---------------------------------------------------------------------------
# Workload-level factors
# ---------------------------------------------------------------------------


def _traffic_variability(factor: WeightedFactor, ctx: EvaluationContext) -> FactorResult:
    pattern = ctx.requirements.traffic_pattern
    if pattern is None or pattern == TrafficPattern.UNKNOWN:
        return _missing(factor, "Traffic pattern was not stated, so variability could not be scored.")
    mapping: dict[TrafficPattern, tuple[float, str]] = {
        TrafficPattern.SPIKY_EVENT: (
            1.0,
            "Spiky, event-driven demand: capacity follows each event instead of a forecast.",
        ),
        TrafficPattern.BURSTY_SCHEDULED: (
            0.7,
            "Scheduled bursts (batches, exam windows, month-end) match pay-per-invocation capacity.",
        ),
        TrafficPattern.DIURNAL: (0.5, "Predictable daily peaks with quiet nights: capacity is released when idle."),
        TrafficPattern.UNPREDICTABLE: (
            0.3,
            "Unpredictable load removes the need to right-size servers, but platform quotas need review.",
        ),
        TrafficPattern.STEADY: (
            -0.4,
            "Flat 24/7 load amortises well on reserved always-on compute, so the cost advantage shrinks.",
        ),
        TrafficPattern.UNKNOWN: (0.0, "Unknown pattern."),
    }
    impact, why = mapping[pattern]
    evidence = [f"Traffic pattern: {_human(pattern.value)}"]
    if ctx.signals.business_hours_only:
        impact = min(1.0, impact + 0.15)
        evidence.append("Usage concentrated in defined hours, leaving idle windows.")
    if not ctx.spike_is_assumed:
        evidence.append(f"Peak load is ~{ctx.spike_factor:.1f}x the average (from stated figures).")
    return _factor_result(factor, ctx, impact, why, evidence, "traffic_pattern")


def _event_driven(factor: WeightedFactor, ctx: EvaluationContext) -> FactorResult:
    signals = ctx.signals
    evidence: list[str] = []
    impact = 0.0
    explained: list[str] = []
    if signals.event_driven is True:
        impact += 0.8
        evidence.append("Work is triggered by events (uploads, submissions, state changes).")
        explained.append("Event-first execution maps directly onto function triggers and queues.")
    elif signals.event_driven is False:
        impact -= 0.5
        evidence.append("Work is described as client-initiated request/response rather than event-driven.")
        explained.append("Synchronous request/response still works serverless, with smaller gains.")
    if signals.messaging_needed:
        impact += 0.3
        evidence.append("Queue or messaging usage identified in the requirements.")
    if signals.scheduled_batch:
        impact += 0.25
        evidence.append("Scheduled batch work identified.")
    if signals.pdf_or_reporting:
        impact += 0.1
        evidence.append("Document/report generation is a natural asynchronous job.")
    if not evidence:
        return _missing(factor, "The description gives no evidence about event-driven behaviour.")
    return _factor_result(
        factor,
        ctx,
        impact,
        " ".join(explained) or "Asynchronous work exists and can be decoupled from the request path.",
        evidence,
        "event_driven",
    )


def _request_shape(factor: WeightedFactor, ctx: EvaluationContext) -> FactorResult:
    ms = ctx.signals.typical_response_ms
    if ms is None:
        return FactorResult(
            id=factor.id,
            name=factor.name,
            weight=factor.weight,
            impact=0.35,
            explanation=(
                "No latency figure was supplied, so the engine assumes an ordinary interactive request/response "
                "workload (sub-second) and records that as an assumption."
            ),
            evidence=["Typical response time not stated; assumed interactive."],
            basis="default",
        )
    if ms <= 100:
        impact, why = 1.0, "Median responses under 100 ms: comfortably inside function execution envelopes."
    elif ms <= 300:
        impact, why = 0.8, "Median responses of a few hundred milliseconds — a natural function workload."
    elif ms <= 1000:
        impact, why = 0.4, "Around one second per request is workable, but cold starts start to matter."
    elif ms <= 3000:
        impact, why = -0.2, "Multi-second requests make per-request billing and gateway timeouts worth planning."
    else:
        impact, why = -0.8, "Requests longer than a few seconds exceed typical synchronous function budgets."
    return _factor_result(factor, ctx, impact, why, [f"Typical response time: {ms} ms"], "typical_response_ms")


def _execution_duration(factor: WeightedFactor, ctx: EvaluationContext) -> FactorResult:
    signals = ctx.signals
    minutes = signals.longest_operation_minutes
    if minutes is None and signals.long_running_jobs is None:
        return _missing(factor, "No information about the longest operation, so long-running work could not be ruled out.")
    if minutes is not None:
        evidence = [f"Longest stated operation: {minutes:g} min"]
        if minutes > 15:
            impact, why = (
                -1.0,
                "Operations above ~15 min exceed typical function execution limits; they belong on a container, "
                "batch or job service rather than inside a short-lived function.",
            )
        elif minutes > 5:
            impact, why = -0.7, "Operations of 5–15 min exceed synchronous function budgets; split them or move to a job service."
        elif minutes > 2:
            impact, why = -0.4, "Multi-minute operations require asynchronous invocation and progress tracking."
        elif minutes > 0.5:
            impact, why = 0.2, "Sub-minute background jobs fit function limits with headroom."
        else:
            impact, why = 0.8, "All stated operations complete quickly enough for short-lived execution."
        basis = "longest_operation_minutes"
    elif signals.long_running_jobs:
        impact, why = -0.8, "Long-running jobs were identified; plan a container or job service for them."
        evidence = ["Long-running background work flagged in the requirements."]
        basis = "long_running_jobs"
    else:
        impact, why = 0.6, "The requirements state there is no long-running processing."
        evidence = ["No long-running work identified."]
        basis = "long_running_jobs"
    return _factor_result(factor, ctx, impact, why, evidence, basis)


def _statelessness(factor: WeightedFactor, ctx: EvaluationContext) -> FactorResult:
    signals = ctx.signals
    evidence: list[str] = []
    impact = 0.0
    if signals.stateful_sessions is True:
        impact -= 0.55
        evidence.append("Sessions carry server-side state.")
    elif signals.stateful_sessions is False:
        impact += 0.5
        evidence.append("Sessions are stateless or token-based.")
    if signals.shared_locking_required:
        impact -= 0.35
        evidence.append("Shared locking or coordination between workers is required.")
    if signals.cache_needed:
        impact += 0.2
        evidence.append("Shared state can live in an external cache or session store.")
    if not evidence:
        return _missing(factor, "Session and coordination behaviour was not described.")
    mitigation = (
        "Externalise session state into a managed cache or a signed token so any instance can serve any request."
        if "server-side state" in " ".join(evidence)
        else None
    )
    return _factor_result(
        factor,
        ctx,
        impact,
        "Stateless request handling lets the platform start and stop instances freely."
        if impact >= 0
        else "Server-side state constrains scale-out and must be externalised before a function design works.",
        evidence,
        "stateful_sessions",
        mitigation=mitigation,
    )


def _persistent_connections(factor: WeightedFactor, ctx: EvaluationContext) -> FactorResult:
    signals = ctx.signals
    evidence: list[str] = []
    impact = 0.0
    if signals.persistent_connections:
        impact -= 0.75
        evidence.append("Long-lived connections (WebSocket / streaming clients) are required.")
    if signals.streaming_ingestion:
        impact -= 0.35
        evidence.append("Continuous stream ingestion was identified.")
    if not evidence:
        return FactorResult(
            id=factor.id,
            name=factor.name,
            weight=factor.weight,
            impact=0.45,
            explanation="No persistent-connection requirement was identified; short-lived connections suit functions.",
            evidence=["No WebSocket/stream requirement stated (treated as an assumption)."],
            basis="default",
        )
    return _factor_result(
        factor,
        ctx,
        impact,
        "Functions end at the close of an invocation, so protocols that must stay open need a managed gateway "
        "or a resident connection service.",
        evidence,
        "persistent_connections",
        mitigation=(
            "Keep only the connection-bearing piece on a managed real-time or small always-on service and let "
            "functions handle the logic behind it."
        ),
    )


def _db_connection_pattern(factor: WeightedFactor, ctx: EvaluationContext) -> FactorResult:
    signals = ctx.signals
    evidence: list[str] = []
    impact = 0.0
    if signals.relational_data or signals.transactional_writes:
        evidence.append("Transactional relational writes identified.")
        if signals.peak_concurrency and signals.peak_concurrency > 2000:
            impact -= 0.6
            evidence.append(
                f"Peak concurrency of {signals.peak_concurrency:,} competes for a managed database connection budget."
            )
        else:
            impact -= 0.1
            evidence.append("Stated concurrency stays inside a typical managed-database connection budget.")
    if signals.key_value_data or signals.document_data:
        impact += 0.3
        evidence.append("NoSQL-style access pattern reduces per-request connection cost.")
    if signals.cache_needed or signals.high_fanout_reads:
        impact += 0.35
        evidence.append("Read fan-out can be served from cache instead of opening more connections.")
    if not evidence:
        return _missing(factor, "Data-access pattern not described, so connection pressure could not be evaluated.")
    return _factor_result(
        factor,
        ctx,
        impact,
        "Each concurrent function can open its own database connection, so scale-out can exhaust the database "
        "before it exhausts the function platform."
        if impact < 0
        else "The data-access pattern does not create unusual connection pressure.",
        evidence,
        "transactional_writes",
        mitigation=(
            "Front the database with a managed connection pooler, cap writer concurrency, and move hot read paths "
            "to a cache or NoSQL store."
            if impact < 0
            else None
        ),
    )


def _storage_fit(factor: WeightedFactor, ctx: EvaluationContext) -> FactorResult:
    signals = ctx.signals
    evidence: list[str] = []
    impact = 0.0
    if signals.object_storage_needed or signals.generated_files or signals.upload_size_mb:
        impact += 0.7
        evidence.append("File artefacts (uploads, PDFs, media) map onto object storage with event triggers.")
    if DataStorageKind.FILE_SHARE.value in ctx.storage_kinds or signals.filesystem_semantics_required:
        impact -= 0.6
        evidence.append("Shared/POSIX-like filesystem access requested — no direct serverless equivalent.")
    if signals.dataset_size_gb and signals.dataset_size_gb > 1000:
        impact -= 0.3
        evidence.append(f"Large stated dataset ({signals.dataset_size_gb:,.0f} GB) affects data-locality design.")
    if not evidence:
        return FactorResult(
            id=factor.id,
            name=factor.name,
            weight=factor.weight,
            impact=0.2,
            explanation="No unusual storage requirement identified; object storage plus a managed database is standard.",
            evidence=["No file-sharing or unusual storage requirement stated."],
            basis="default",
        )
    return _factor_result(
        factor,
        ctx,
        impact,
        "Object storage integrates natively with event-driven compute; filesystem semantics do not.",
        evidence,
        "object_storage_needed",
    )


def _resource_intensity(factor: WeightedFactor, ctx: EvaluationContext) -> FactorResult:
    signals = ctx.signals
    if signals.gpu_required:
        return _factor_result(
            factor,
            ctx,
            -1.0,
            "GPU-backed work is poorly served by generic short-lived functions; a GPU container or specialised "
            "batch service is the honest recommendation.",
            ["GPU acceleration requested."],
            "gpu_required",
        )
    if signals.cpu_or_memory_intensive:
        return _factor_result(
            factor,
            ctx,
            -0.7,
            "Heavy sustained compute makes per-invocation pricing and memory ceilings unfavourable.",
            ["CPU/memory-intensive processing identified."],
            "cpu_or_memory_intensive",
        )
    if signals.custom_runtime_required:
        return _factor_result(
            factor,
            ctx,
            -0.4,
            "Non-standard runtimes force layer or container image packaging and constrain the environment.",
            ["Custom runtime or native dependencies identified."],
            "custom_runtime_required",
        )
    return _factor_result(
        factor,
        ctx,
        0.5,
        "Typical web/API code sizes fit inside managed function runtimes.",
        ["No CPU/GPU-bound or exotic-runtime workload identified."],
        "cpu_or_memory_intensive",
        fallback_basis="default",
    )


def _availability(factor: WeightedFactor, ctx: EvaluationContext) -> FactorResult:
    expectation = ctx.requirements.availability
    mapping: dict[AvailabilityExpectation, tuple[float, str]] = {
        AvailabilityExpectation.CRITICAL: (
            -0.3,
            "A critical SLO demands explicit quota, throttling and multi-AZ verification on a managed runtime.",
        ),
        AvailabilityExpectation.HIGH: (0.1, "High availability is achievable; async retry paths need review."),
        AvailabilityExpectation.STANDARD: (0.4, "Standard expectations are met by multi-AZ managed services."),
        AvailabilityExpectation.BEST_EFFORT: (0.6, "Best-effort availability removes the platform's hardest guarantees."),
        AvailabilityExpectation.UNKNOWN: (0.0, "Availability expectation unknown."),
    }
    if expectation is None or expectation == AvailabilityExpectation.UNKNOWN:
        return _missing(factor, "Availability expectation was not stated.")
    impact, why = mapping[expectation]
    return _factor_result(
        factor, ctx, impact, why, [f"Availability expectation: {_human(expectation.value)}"], "availability"
    )


def _cold_start(factor: WeightedFactor, ctx: EvaluationContext) -> FactorResult:
    signals = ctx.signals
    if signals.cold_start_sensitive or signals.startup_latency_sensitive:
        return _factor_result(
            factor,
            ctx,
            -0.8,
            "The workload is latency-critical on first request, so cold starts need provisioned concurrency.",
            ["Cold-start / start-up sensitivity identified."],
            "cold_start_sensitive",
            mitigation="Provisioned concurrency, warm keep-alives, or a small resident service for the hot path.",
        )
    budget = signals.latency_budget_ms
    if budget is not None:
        if budget <= 100:
            impact, why = -0.5, f"A {budget} ms budget leaves little room for a cold start."
        elif budget <= 400:
            impact, why = -0.1, f"A {budget} ms budget is achievable with warm-up strategies."
        else:
            impact, why = 0.4, f"A {budget} ms budget absorbs normal platform start-up variance."
        return _factor_result(factor, ctx, impact, why, [f"Latency budget: {budget} ms"], "latency_budget_ms")
    return FactorResult(
        id=factor.id,
        name=factor.name,
        weight=factor.weight,
        impact=0.2,
        explanation="No latency budget stated; cold-start impact assumed low and recorded as an assumption.",
        evidence=["Latency budget not stated."],
        basis="default",
    )


def _runtime_constraints(factor: WeightedFactor, ctx: EvaluationContext) -> FactorResult:
    signals = ctx.signals
    evidence: list[str] = []
    impact = 0.5
    if signals.custom_runtime_required:
        impact = -0.7
        evidence.append("Custom/native runtime or OS dependency identified.")
    if signals.multi_tenant:
        evidence.append("Multi-tenant isolation requirement noted.")
        impact -= 0.1
    if signals.compliance_regime:
        impact = min(impact, -0.35)
        evidence.append(f"Stated compliance considerations: {signals.compliance_regime}.")
    if not evidence:
        evidence.append("No unusual runtime, language or compliance constraint identified.")
    return _factor_result(
        factor,
        ctx,
        impact,
        "Managed runtimes constrain languages, package size and the execution environment; those constraints "
        "decide this factor.",
        evidence,
        "custom_runtime_required",
        fallback_basis="default",
    )


def _human(value: str) -> str:
    return value.replace("_", " ")


WORKLOAD_FACTORS: list[WeightedFactor] = [
    WeightedFactor("traffic_variability", "Traffic variability", 0.16, _traffic_variability,
                   "How bursty or idle-heavy is the demand?"),
    WeightedFactor("event_driven_nature", "Event-driven work", 0.12, _event_driven,
                   "Is work triggered by events rather than by a waiting client?"),
    WeightedFactor("request_response_shape", "Request/response shape", 0.10, _request_shape,
                   "How long does one interaction take?"),
    WeightedFactor("execution_duration", "Execution duration", 0.14, _execution_duration,
                   "Does any operation exceed function time limits?"),
    WeightedFactor("statelessness", "Stateless execution", 0.10, _statelessness,
                   "Can any instance serve any request?"),
    WeightedFactor("persistent_connections", "Persistent connections", 0.08, _persistent_connections,
                   "Are long-lived sockets required?"),
    WeightedFactor("database_connection_pattern", "Database connection pattern", 0.07, _db_connection_pattern,
                   "Will scale-out exhaust database connections?"),
    WeightedFactor("storage_fit", "Storage fit", 0.05, _storage_fit,
                   "Does storage need filesystem semantics?"),
    WeightedFactor("resource_intensity", "Resource intensity", 0.06, _resource_intensity,
                   "Is the workload CPU/GPU bound?"),
    WeightedFactor("availability_requirement", "Availability requirement", 0.05, _availability,
                   "What availability is promised?"),
    WeightedFactor("cold_start_sensitivity", "Cold-start sensitivity", 0.04, _cold_start,
                   "How sensitive is user experience to start-up latency?"),
    WeightedFactor("runtime_constraints", "Runtime constraints", 0.03, _runtime_constraints,
                   "Are runtime, language or compliance constraints present?"),
]

WORKLOAD_FACTORS_BY_ID = {factor.id: factor for factor in WORKLOAD_FACTORS}

# Fail fast at import time if someone edits the table without rebalancing it.
_WEIGHT_SUM = sum(factor.weight for factor in WORKLOAD_FACTORS)
assert abs(_WEIGHT_SUM - 1.0) < 1e-9, f"workload factor weights must sum to 1.0 (got {_WEIGHT_SUM})"

COMPONENT_FACTOR_WEIGHTS: dict[str, float] = {
    "trigger": 0.28,
    "duration": 0.26,
    "state": 0.18,
    "connections": 0.12,
    "runtime": 0.10,
    "fixed_overhead": 0.06,
}

BANDS: list[tuple[float, SuitabilityOutcome]] = [
    (78.0, SuitabilityOutcome.STRONG_CANDIDATE),
    (62.0, SuitabilityOutcome.SUITABLE_WITH_MODIFICATIONS),
    (45.0, SuitabilityOutcome.PARTIAL_ADOPTION),
    (0.0, SuitabilityOutcome.POOR_CANDIDATE),
]

BAND_DESCRIPTIONS: dict[SuitabilityOutcome, str] = {
    SuitabilityOutcome.STRONG_CANDIDATE: (
        "The workload fits a managed function platform with little architectural compromise."
    ),
    SuitabilityOutcome.SUITABLE_WITH_MODIFICATIONS: (
        "Suitable once specific coupling or duration issues are restructured (async jobs, externalised state)."
    ),
    SuitabilityOutcome.PARTIAL_ADOPTION: (
        "Adopt serverless for the event-driven and spiky pieces; keep the remainder on containers or managed services."
    ),
    SuitabilityOutcome.POOR_CANDIDATE: (
        "The stated constraints conflict with short-lived per-invocation execution; a serverless-first design would "
        "need significant re-engineering."
    ),
    SuitabilityOutcome.FURTHER_ASSESSMENT: (
        "Too many deciding factors lack evidence, so the numeric score is provisional."
    ),
}


def evaluate_workload(ctx: EvaluationContext) -> list[FactorResult]:
    """Evaluate every workload-level factor exactly once."""
    results: list[FactorResult] = []
    for factor in WORKLOAD_FACTORS:
        try:
            results.append(factor.evaluate(factor, ctx))
        except Exception:  # pragma: no cover - a broken factor must not kill the pipeline
            results.append(
                FactorResult(
                    id=factor.id,
                    name=factor.name,
                    weight=factor.weight,
                    impact=0.0,
                    explanation="This factor could not be evaluated with the supplied inputs and was treated as neutral.",
                    basis="missing",
                )
            )
    return results


def score_from_factors(factors: list[FactorResult]) -> tuple[float, float, list[str]]:
    """Return (score, missing_weight, missing_factor_ids)."""
    total = sum(factor.contribution for factor in factors)
    score = round(100 * (0.5 + 0.5 * total), 1)
    score = max(0.0, min(100.0, score))
    missing_weight = round(sum(f.weight for f in factors if f.basis == "missing"), 4)
    missing_ids = [f.id for f in factors if f.basis == "missing"]
    return score, missing_weight, missing_ids


def band_for(score: float) -> SuitabilityOutcome:
    for threshold, outcome in BANDS:
        if score >= threshold:
            return outcome
    return SuitabilityOutcome.POOR_CANDIDATE  # pragma: no cover - last band starts at 0


def overall_outcome(score: float, missing_weight: float) -> tuple[SuitabilityOutcome, bool]:
    """Score band, overridden when evidence is too thin to justify a verdict."""
    if missing_weight >= MISSING_WEIGHT_LIMIT:
        return SuitabilityOutcome.FURTHER_ASSESSMENT, True
    return band_for(score), False


def recommended_pattern(
    outcome: SuitabilityOutcome,
    factors: list[FactorResult],
    component_targets: dict[str, DeploymentTarget],
) -> RecommendedPattern:
    if outcome == SuitabilityOutcome.FURTHER_ASSESSMENT:
        return RecommendedPattern.FURTHER_ASSESSMENT
    serverless_share = sum(1 for target in component_targets.values() if target == DeploymentTarget.SERVERLESS_FUNCTION)
    non_serverless = [
        target
        for target in component_targets.values()
        if target not in {DeploymentTarget.SERVERLESS_FUNCTION, DeploymentTarget.MANAGED_SERVICE}
    ]
    by_id = {factor.id: factor for factor in factors}
    heavy_compute = by_id.get("resource_intensity") is not None and by_id["resource_intensity"].impact <= -0.65
    long_running = by_id.get("execution_duration") is not None and by_id["execution_duration"].impact <= -0.65

    if outcome == SuitabilityOutcome.STRONG_CANDIDATE and serverless_share:
        return RecommendedPattern.SERVERLESS_FIRST
    if outcome == SuitabilityOutcome.SUITABLE_WITH_MODIFICATIONS:
        return RecommendedPattern.HYBRID if non_serverless else RecommendedPattern.SERVERLESS_WHERE_SUITABLE
    if outcome == SuitabilityOutcome.PARTIAL_ADOPTION:
        return RecommendedPattern.HYBRID
    if heavy_compute or long_running:
        return RecommendedPattern.MANAGED_CONTAINER
    return RecommendedPattern.CONVENTIONAL_KEEP


# ---------------------------------------------------------------------------
# Component-level scoring
# ---------------------------------------------------------------------------


def evaluate_component(
    traits: ComponentTraits,
    *,
    spike_factor: float = 1.35,
    always_on_platform_penalty: bool = False,
) -> list[FactorResult]:
    """Score one logical component on the same formula with a component factor set."""
    weights = COMPONENT_FACTOR_WEIGHTS
    factors: list[FactorResult] = []

    trigger_map = {
        ComponentRuntime.EVENT_TRIGGERED: (1.0, "Natively triggered by an event, upload or queue message."),
        ComponentRuntime.REQUEST_RESPONSE: (0.55, "Synchronous request/response workload; fits HTTP-fronted functions."),
        ComponentRuntime.STREAMING: (-0.6, "Continuous stream consumption needs a resident consumer."),
        ComponentRuntime.ALWAYS_ON: (-0.8, "Always-on process: a function cannot stay resident between invocations."),
        ComponentRuntime.SCHEDULED_BATCH: (0.7, "Scheduled batch execution maps onto a timed function or job runner."),
        ComponentRuntime.LONG_RUNNING: (-0.9, "Long-running execution exceeds function budgets."),
        ComponentRuntime.STATIC: (0.3, "Static content is served by edge/object storage rather than compute."),
        ComponentRuntime.MANAGED: (0.2, "A managed service absorbs this responsibility without custom code."),
    }
    impact, why = trigger_map[traits.runtime]
    if traits.event_triggered and traits.runtime == ComponentRuntime.REQUEST_RESPONSE:
        impact = max(impact, 0.8)
        why = "Invoked by an event source and also addressable over HTTP."
    factors.append(
        FactorResult("trigger", "Trigger model", weights["trigger"], impact, why,
                     [f"Component runtime: {traits.runtime.value.replace('_', ' ')}"], "inferred")
    )

    duration_map = {
        DurationProfile.SUB_SECOND: (1.0, "Completes in under a second."),
        DurationProfile.FEW_SECONDS: (0.5, "Runs for a few seconds — inside function limits."),
        DurationProfile.MINUTES: (-0.8, "Runs for minutes; synchronous invocation would sit near the timeout."),
        DurationProfile.INDEFINITE: (-1.0, "Runs indefinitely and cannot be modelled as a single function invocation."),
        DurationProfile.UNSPECIFIED: (0.0, "Execution duration not established for this component."),
    }
    dur_impact, dur_why = duration_map[traits.duration]
    factors.append(
        FactorResult("duration", "Execution duration", weights["duration"], dur_impact, dur_why,
                     [f"Duration profile: {traits.duration.value.replace('_', ' ')}"],
                     "inferred" if traits.duration != DurationProfile.UNSPECIFIED else "missing")
    )

    state_impact = -0.7 if traits.stateful else 0.6
    factors.append(
        FactorResult("state", "State management", weights["state"], state_impact,
                     "Holds local state that must be externalised before serverless execution."
                     if traits.stateful
                     else "Stateless — the platform may start or stop instances freely.",
                     [f"Stateful: {'yes' if traits.stateful else 'no'}"], "inferred")
    )

    conn_impact = -0.9 if traits.persistent_connections else 0.4
    factors.append(
        FactorResult("connections", "Connection model", weights["connections"], conn_impact,
                     "Requires sockets that outlive a single invocation." if traits.persistent_connections
                     else "Short-lived connections only.",
                     [f"Persistent connections: {'yes' if traits.persistent_connections else 'no'}"], "inferred")
    )

    if traits.gpu_required:
        rt_impact, rt_why = -1.0, "GPU acceleration is required."
    elif traits.cpu_or_memory_intensive:
        rt_impact, rt_why = -0.6, "Compute or memory intensive work."
    elif traits.custom_runtime:
        rt_impact, rt_why = -0.5, "Custom runtime or native dependencies required."
    else:
        rt_impact, rt_why = 0.5, "Standard managed runtime supported."
    factors.append(
        FactorResult("runtime", "Runtime constraints", weights["runtime"], rt_impact, rt_why,
                     [f"gpu={traits.gpu_required}, cpu_or_memory_intensive={traits.cpu_or_memory_intensive}, "
                      f"custom_runtime={traits.custom_runtime}"], "inferred")
    )

    if traits.always_on or always_on_platform_penalty:
        fixed_impact, fixed_why = -0.5, "Constant background activity removes the idle-time advantage."
    elif spike_factor >= 1.6:
        fixed_impact, fixed_why = 0.8, f"Peak load is ~{spike_factor:.1f}x average, so per-request billing wins."
    elif spike_factor >= 1.2:
        fixed_impact, fixed_why = 0.4, f"Peak/average ratio of ~{spike_factor:.1f}x still favours elastic capacity."
    else:
        fixed_impact, fixed_why = -0.2, "Nearly flat utilisation: reserved capacity remains competitive."
    factors.append(
        FactorResult("fixed_overhead", "Utilisation economics", weights["fixed_overhead"], fixed_impact, fixed_why,
                     [f"Peak/average factor: {spike_factor:.2f}" + (" (assumed)" if always_on_platform_penalty else "")],
                     "inferred")
    )
    return factors


def component_score_and_outcome(factors: list[FactorResult]) -> tuple[float, SuitabilityOutcome, list[str]]:
    score, missing_weight, missing_ids = score_from_factors(factors)
    if missing_weight >= 0.34:
        return score, SuitabilityOutcome.FURTHER_ASSESSMENT, missing_ids
    return score, band_for(score), missing_ids


def target_for_component(
    outcome: SuitabilityOutcome,
    traits: ComponentTraits,
    factors: list[FactorResult],
) -> DeploymentTarget:
    """Pick the realization for one component, explaining the override if any."""
    by_id = {factor.id: factor for factor in factors}
    if traits.runtime in {ComponentRuntime.STATIC, ComponentRuntime.MANAGED}:
        return DeploymentTarget.MANAGED_SERVICE
    if traits.gpu_required or traits.custom_runtime:
        return DeploymentTarget.CONTAINER
    if traits.runtime == ComponentRuntime.LONG_RUNNING:
        return DeploymentTarget.CONTAINER
    if traits.gpu_required and traits.custom_runtime and traits.cpu_or_memory_intensive:
        return DeploymentTarget.VIRTUAL_MACHINE
    if traits.duration == DurationProfile.INDEFINITE:
        # A resident service belongs on a container platform; a VM is only
        # recommended when the container options are also excluded.
        return DeploymentTarget.CONTAINER
    if by_id["duration"].impact <= -0.65:
        return DeploymentTarget.CONTAINER
    if traits.persistent_connections:
        return DeploymentTarget.CONTAINER
    if outcome in {SuitabilityOutcome.STRONG_CANDIDATE, SuitabilityOutcome.SUITABLE_WITH_MODIFICATIONS}:
        return DeploymentTarget.SERVERLESS_FUNCTION
    if outcome == SuitabilityOutcome.PARTIAL_ADOPTION:
        return DeploymentTarget.MANAGED_SERVICE
    if outcome == SuitabilityOutcome.FURTHER_ASSESSMENT:
        return DeploymentTarget.REVIEW_REQUIRED
    return DeploymentTarget.RETAIN_AS_IS


def aggregate_score(workload_score: float, component_scores: list[float]) -> float:
    """Blend workload-level and component-level evidence: 55% / 45%.

    Component scores are averaged with equal weight; a request-heavy architecture does
    not get to hide behind one badly suited background job, and one ideal component
    cannot rescue an unsuitable workload shape.
    """
    if not component_scores:
        return round(workload_score, 1)
    component_mean = sum(component_scores) / len(component_scores)
    return round(0.55 * workload_score + 0.45 * component_mean, 1)
