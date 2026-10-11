"""The authoritative NYX serverless suitability engine.

This is the *only* module in the repository that composes a serverless
suitability verdict.  The rules themselves (factor tables, weights, bands,
evidence gates) live in the pure rule pack `app.rules.suitability_rules`; this
module is the single composition layer that turns them into a
`SuitabilityReport`.

Public interface
----------------
``evaluate_suitability(requirements, signals, plans) -> SuitabilityReport``
    The authoritative entry point.  Validates its inputs, evaluates the workload
    and each scoreable component once, blends the two scores, applies the
    evidence-quality override and returns a fully explained report.

``SuitabilityService``
    A thin, stateless object wrapper kept for callers that prefer an instance
    (the analysis pipeline holds one).  ``SuitabilityService.assess`` delegates
    to ``evaluate_suitability``; there is no second implementation.

``report_from_service``
    Backwards-compatible alias of ``evaluate_suitability``.

Guarantees
----------
* **Deterministic.** Same normalised input → byte-identical report.  No
  randomness, no clock, no model call, no network call, no mutable module or
  instance state that survives a call.
* **Evidence-gated.** A factor with no supporting evidence contributes 0 and is
  reported as ``missing``; it is never defaulted to favourable.  When missing
  evidence reaches ``MISSING_WEIGHT_LIMIT`` the outcome becomes
  ``FURTHER_ASSESSMENT_REQUIRED`` and the blended score is published as
  ``provisional_score`` instead of as a verdict.
* **Hybrid-capable.** ``recommended_pattern`` can return ``hybrid`` or
  ``managed_container``, and per-component recommendations can place some
  components on functions and others on containers.  The engine does not
  classify every workload as serverless-friendly.
* **Dependency-light.** Imports the schemas, the rule pack and (for tier
  lookup) ``app.services.component_identifier``.  It never imports API routes,
  persistence, the cloud catalogue, the AI provider or any frontend code.

Full methodology, factor rationale and scoring table:
``docs/backend/SUITABILITY_ENGINE.md``.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.rules.suitability_rules import (
    BANDS,
    BAND_DESCRIPTIONS,
    EvaluationContext,
    FactorResult,
    RULE_PACK_VERSION,
    WEIGHT_RATIONALE,
    aggregate_score,
    component_score_and_outcome,
    evaluate_component,
    evaluate_workload,
    overall_outcome,
    recommended_pattern,
    score_from_factors,
    target_for_component,
)
from app.schemas.architecture import ComponentPlan
from app.schemas.common import (
    ComponentTier,
    DeploymentTarget,
    RecommendedPattern,
    SuitabilityOutcome,
)
from app.schemas.reports import (
    ComponentSuitability,
    SuitabilityBand,
    SuitabilityFactor,
    SuitabilityMethodology,
    SuitabilityReport,
)
from app.schemas.requirements import ApplicationRequirements, RequirementSignals
from app.services.component_identifier import TIER_BY_TYPE

#: Only components whose *compute shape* is a genuine serverless decision are
#: scored here.  Queues, streams, notification channels, identity and data stores
#: are managed services by definition in this model — scoring them as function
#: candidates would be misleading.
SCORED_TIERS = {ComponentTier.APPLICATION, ComponentTier.PROCESSING}

FACTOR_LABELS = {
    "traffic_variability": "How uneven the demand is",
    "event_driven_nature": "How much work is triggered by events",
    "request_response_shape": "How long one interaction takes",
    "execution_duration": "Whether any operation outlives a function",
    "statelessness": "Whether compute can be started and stopped freely",
    "persistent_connections": "Whether sockets must stay open",
    "database_connection_pattern": "Whether scale-out exhausts database connections",
    "storage_fit": "Whether storage fits object semantics",
    "resource_intensity": "How compute/GPU bound the work is",
    "availability_requirement": "How strict the availability promise is",
    "cold_start_sensitivity": "How much start-up latency matters",
    "runtime_constraints": "How constrained the runtime is",
}

HEADLINES: dict[SuitabilityOutcome, str] = {
    SuitabilityOutcome.STRONG_CANDIDATE: "Strong candidate for a serverless-first design",
    SuitabilityOutcome.SUITABLE_WITH_MODIFICATIONS: "Suitable once specific work is restructured",
    SuitabilityOutcome.PARTIAL_ADOPTION: "Partial adoption: serverless where it earns its place",
    SuitabilityOutcome.POOR_CANDIDATE: "Poor candidate for the proposed serverless design",
    SuitabilityOutcome.FURTHER_ASSESSMENT: "Further assessment required before committing",
}

PATTERN_NOTES: dict[RecommendedPattern, str] = {
    RecommendedPattern.SERVERLESS_FIRST: "Function-first across the request path, with managed data services.",
    RecommendedPattern.SERVERLESS_WHERE_SUITABLE: "Functions on the request path; a couple of pieces stay resident.",
    RecommendedPattern.HYBRID: "A hybrid design: functions plus a container or job service for the heavy work.",
    RecommendedPattern.MANAGED_CONTAINER: "Container- or job-led design; the workload shape fights short-lived execution.",
    RecommendedPattern.CONVENTIONAL_KEEP: "Keep the conventional design and revisit when the workload changes shape.",
    RecommendedPattern.FURTHER_ASSESSMENT: "Answer the open questions first; the recommendation is not yet safe.",
}


def _to_schema_factor(result: FactorResult) -> SuitabilityFactor:
    text = result.explanation
    if result.mitigation:
        text = f"{text} Mitigation: {result.mitigation}"
    return SuitabilityFactor(
        id=result.id,
        name=result.name,
        weight=result.weight,
        impact=result.impact,
        contribution=result.contribution,
        evidence=result.evidence,
        explanation=text,
        direction=result.direction,
        basis=result.basis,  # type: ignore[arg-type]
    )


class SuitabilityService:
    """Stateless wrapper around :func:`evaluate_suitability`.

    Kept because the analysis pipeline holds a service instance per stage.  It
    carries no per-call state, so one instance may be shared freely across
    threads and repeated calls.  ``assess`` contains no logic of its own: the
    authoritative implementation is :func:`evaluate_suitability`.
    """

    version = RULE_PACK_VERSION

    def assess(
        self,
        requirements: ApplicationRequirements,
        signals: RequirementSignals,
        plans: list[ComponentPlan],
    ) -> SuitabilityReport:
        """Evaluate suitability.  Delegates to the authoritative entry point."""
        return evaluate_suitability(requirements, signals, plans)

    @staticmethod
    def _spike_factor(signals: RequirementSignals) -> float:
        """Retained for callers that reached the helper through the service."""
        return spike_factor_for(signals)


def _validate_inputs(
    requirements: ApplicationRequirements,
    signals: RequirementSignals,
    plans: Iterable[ComponentPlan],
) -> list[ComponentPlan]:
    """Reject unsupported inputs loudly instead of producing a misleading report.

    The pipeline is the only production caller and always passes well-formed
    arguments, but this is the authoritative scoring path: a wrongly typed or
    partially built argument must fail here rather than be silently coerced into
    a score.

    Returns the plans as a materialised ``list`` so that the rest of the
    evaluation iterates a stable sequence exactly once, whatever the caller
    passed (list, tuple, generator).
    """
    if not isinstance(requirements, ApplicationRequirements):
        raise TypeError(
            f"evaluate_suitability() requires ApplicationRequirements, got {type(requirements).__name__}"
        )
    if not isinstance(signals, RequirementSignals):
        raise TypeError(
            f"evaluate_suitability() requires RequirementSignals, got {type(signals).__name__}"
        )
    if isinstance(plans, (str, bytes)) or not isinstance(plans, Iterable):
        raise TypeError(
            f"evaluate_suitability() requires an iterable of ComponentPlan, got {type(plans).__name__}"
        )
    materialised = list(plans)
    for index, plan in enumerate(materialised):
        if not isinstance(plan, ComponentPlan):
            raise TypeError(f"plans[{index}] must be a ComponentPlan, got {type(plan).__name__}")
    return materialised


def evaluate_suitability(
    requirements: ApplicationRequirements,
    signals: RequirementSignals,
    plans: Iterable[ComponentPlan],
) -> SuitabilityReport:
    """Authoritative serverless suitability evaluation.

    Parameters
    ----------
    requirements:
        A validated :class:`ApplicationRequirements` — the user- and
        template-declared facts, already enriched by the requirement extractor.
    signals:
        The matching :class:`RequirementSignals` — the derived workload
        characteristics the factors actually read.
    plans:
        The identified :class:`ComponentPlan` values (any iterable; it is
        materialised once at the start of the call).  Only plans whose tier is in
        ``SCORED_TIERS`` are scored; managed rails (queues, data stores, identity,
        notification, observability) are excluded on purpose.

    Returns
    -------
    SuitabilityReport
        Score on a 0-100 scale, outcome band, recommended pattern, every factor
        with its weight/impact/contribution/evidence/basis, per-component
        verdicts, missing inputs, assumptions-driving caveats and the
        methodology block.

    Raises
    ------
    TypeError
        If any argument is not of the documented type.  Unsupported workload
        attributes are rejected rather than silently ignored.

    The call is pure: it does not mutate its arguments, and repeated calls with
    equal inputs return equal reports.
    """
    plans = _validate_inputs(requirements, signals, plans)

    ctx = EvaluationContext(
        requirements=requirements,
        signals=signals,
        spike_factor=spike_factor_for(signals),
        spike_is_assumed=signals.peak_requests_per_minute is None,
    )

    workload_factors = evaluate_workload(ctx)
    workload_score, workload_missing_weight, _workload_missing = score_from_factors(workload_factors)

    scored_plans = [plan for plan in plans if tier_of(plan) in SCORED_TIERS]
    component_results: list[ComponentSuitability] = []
    component_missing_weights: list[float] = []
    for plan in scored_plans:
        # Each component is evaluated exactly once; the missing weight used for
        # the evidence gate below is taken from these same factors so the two can
        # never disagree.
        factors = evaluate_component(
            plan.traits,
            spike_factor=ctx.spike_factor,
            always_on_platform_penalty=plan.traits.always_on and signals.longest_operation_minutes is None,
        )
        component_missing_weights.append(score_from_factors(factors)[1])
        score, outcome, missing = component_score_and_outcome(factors)
        target = target_for_component(outcome, plan.traits, factors)
        reason = target_reason(target, outcome, plan, factors)
        component_results.append(
            ComponentSuitability(
                component_id=plan.id or plan.type.value,
                component_label=plan.label or plan.type.value,
                score=score,
                outcome=outcome,
                recommendation=target,
                recommendation_reason=reason,
                factors=[_to_schema_factor(item) for item in factors],
                reasons_for=[f.explanation for f in factors if f.direction == "positive"][:6],
                reasons_against=[f.explanation for f in factors if f.direction == "negative"][:6],
                missing_inputs=missing,
                provisional=outcome == SuitabilityOutcome.FURTHER_ASSESSMENT,
            )
        )

    component_scores = [item.score for item in component_results]
    combined = aggregate_score(workload_score, component_scores)
    total_missing_weight = max(workload_missing_weight, _mean(component_missing_weights))
    outcome, provisional = overall_outcome(combined, total_missing_weight)
    # When nothing was scoreable there is no component evidence to weigh, so the
    # pattern rule is given a single managed-service slot rather than an empty set.
    targets = {
        item.component_id: item.recommendation for item in component_results
    } or {DeploymentTarget.MANAGED_SERVICE: DeploymentTarget.MANAGED_SERVICE}
    pattern = recommended_pattern(outcome, workload_factors, targets)

    positives = [f for f in workload_factors if f.direction == "positive"]
    negatives = [f for f in workload_factors if f.direction == "negative"]
    supporting = _dedupe([evidence for factor in positives for evidence in factor.evidence])
    concerns = _dedupe([f"{factor.name}: {factor.explanation}" for factor in negatives])
    missing_labels = [factor.name for factor in workload_factors if factor.basis == "missing"]
    for plan, item in zip(scored_plans, component_results):
        for factor_id in item.missing_inputs:
            label = f"{item.component_label}: {FACTOR_LABELS.get(factor_id, factor_id.replace('_', ' '))}"
            if label not in missing_labels:
                missing_labels.append(label)

    caveats = [
        "Scores are heuristic estimates derived from the recorded rule weights and the stated inputs; "
        "they are not an industry benchmark and do not guarantee a successful migration.",
        "Provider quotas, regional availability and current service limits must be re-verified before "
        "any implementation decision.",
    ]
    if provisional:
        caveats.insert(
            0,
            f"{total_missing_weight:.0%} of the deciding factor weight had no supporting evidence, so the "
            "numeric score is provisional and should not be quoted as a conclusion.",
        )

    rationale = _build_rationale(outcome, combined, positives, negatives, provisional, total_missing_weight, pattern)

    return SuitabilityReport(
        score=combined if not provisional else round(workload_score, 1),
        provisional_score=combined if provisional else None,
        outcome=outcome,
        headline=HEADLINES[outcome],
        rationale=rationale,
        recommended_pattern=pattern,
        factors=[_to_schema_factor(item) for item in workload_factors],
        supporting_evidence=supporting,
        concerns=concerns,
        components=component_results,
        methodology=SuitabilityMethodology(
            formula=(
                "score = 100 x (0.5 + 0.5 x Σ(weight_i x impact_i)), impact_i in [-1, +1]. "
                "Overall = 0.55 x workload score + 0.45 x mean of scored component results "
                "(tiers: application and processing; managed services are excluded because their "
                "realization is a managed service by definition)."
            ),
            band_source=f"Rule pack {RULE_PACK_VERSION} — fixed band thresholds, not an external standard.",
            weight_source=WEIGHT_RATIONALE,
            bands=[
                SuitabilityBand(
                    outcome=outcome_band,
                    min_score=threshold,
                    description=BAND_DESCRIPTIONS[outcome_band],
                )
                for threshold, outcome_band in _bands()
            ],
            notes=[
                "A factor with no evidence contributes 0 (neutral) and is listed as missing rather than defaulted to favourable.",
                "When missing evidence exceeds 30% of total weight, the outcome becomes 'further assessment required'.",
                PATTERN_NOTES[pattern],
            ],
        ),
        missing_inputs=missing_labels,
        caveats=caveats,
    )


def tier_of(plan: ComponentPlan) -> ComponentTier:
    """Architectural tier of a plan, via the shared component classifier.

    `TIER_BY_TYPE` is imported at module level: the suitability path must not
    carry a second, divergent mapping of component type to tier.
    """
    return TIER_BY_TYPE[plan.type]


def spike_factor_for(signals: RequirementSignals) -> float:
    """Peak-to-average traffic multiplier, derived from stated figures when possible.

    Uses the same active-days-per-month convention as the cost and requirement
    rules (26 days) and clamps to a floor of 1.0.  When either figure is absent
    the traffic-pattern factor falls back to its documented assumption and
    ``EvaluationContext.spike_is_assumed`` records that fact in the report.
    """
    if signals.monthly_requests and signals.peak_requests_per_minute:
        average = signals.monthly_requests / (26 * 24 * 60)
        if average > 0:
            return round(max(1.0, signals.peak_requests_per_minute / average), 2)
    return 1.35


def _mean(values: list[float]) -> float:
    """Mean of component missing weights, rounded as the previous version did."""
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _bands() -> list[tuple[float, SuitabilityOutcome]]:
    """Band thresholds, ascending by score.

    Ordered ascending here because `methodology.bands` reads as a ladder from the
    floor upward.  The rule pack stores `BANDS` descending (for lookup by
    `band_for`) and the `/api/meta` endpoint republishes that descending order;
    the thresholds themselves come from `BANDS` and are never restated.
    """
    return sorted(BANDS, key=lambda item: item[0])


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return seen


def target_reason(
    target: DeploymentTarget,
    outcome: SuitabilityOutcome,
    plan: ComponentPlan,
    factors: list[FactorResult],
) -> str:
    by_id = {factor.id: factor for factor in factors}
    duration = by_id.get("duration")
    if target == DeploymentTarget.CONTAINER:
        if plan.traits.gpu_required:
            return "GPU acceleration is required, which the short-lived function runtime cannot provide economically."
        if plan.traits.duration.value in {"indefinite", "minutes"} or (duration and duration.impact <= -0.65):
            return (
                "Execution outlives the managed function budget, so it is placed on a container or job runtime "
                "that can run for as long as the work needs."
            )
        if plan.traits.persistent_connections:
            return "It must hold client sockets open across many requests, which a function invocation cannot do."
        return "Runtime or packaging constraints make a container the honest fit rather than a function."
    if target == DeploymentTarget.SERVERLESS_FUNCTION:
        return (
            "Event-triggered, short, stateless execution — the shape the platform is designed for; scale comes "
            "for free and idle cost is zero."
        )
    if target == DeploymentTarget.MANAGED_SERVICE:
        return "This responsibility is better absorbed by a managed service than by code the team owns."
    if target == DeploymentTarget.VIRTUAL_MACHINE:
        return "A stated constraint (licensing, OS control or protocol) rules out the managed options for now."
    if target == DeploymentTarget.REVIEW_REQUIRED:
        return "Evidence is too thin to choose confidently; verify the missing inputs before committing."
    return "No change is recommended for this component in the proposed design."


def _build_rationale(
    outcome: SuitabilityOutcome,
    score: float,
    positives: list[FactorResult],
    negatives: list[FactorResult],
    provisional: bool,
    missing_weight: float,
    pattern: RecommendedPattern,
) -> str:
    parts: list[str] = []
    if provisional:
        parts.append(
            f"The blended score is {score:.0f}/100, but {missing_weight:.0%} of the deciding weight had no "
            "supporting statement in your input, so no firm recommendation is made."
        )
    else:
        parts.append(f"The blended score is {score:.0f}/100 from {len(positives) + len(negatives)} weighted factors.")
    if positives:
        parts.append(
            "Favourable: " + "; ".join(f"{factor.name.lower()} ({factor.explanation.split('.')[0].lower()})" for factor in positives[:3])
            + "."
        )
    if negatives:
        parts.append(
            "Against: " + "; ".join(f"{factor.name.lower()} ({factor.explanation.split('.')[0].lower()})" for factor in negatives[:3])
            + "."
        )
    parts.append(BAND_DESCRIPTIONS[outcome])
    parts.append(PATTERN_NOTES[pattern])
    return " ".join(parts)


def report_from_service(
    requirements: ApplicationRequirements, signals: RequirementSignals, plans: list[ComponentPlan]
) -> SuitabilityReport:
    """Backwards-compatible alias of :func:`evaluate_suitability`.

    Retained so previously written callers keep working.  It performs the same
    evaluation — there is deliberately no second implementation behind it.
    """
    return evaluate_suitability(requirements, signals, plans)
