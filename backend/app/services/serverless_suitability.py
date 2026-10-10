"""Serverless suitability stage.

Composes the rule pack in `app.rules.suitability_rules` into a
`SuitabilityReport`: workload-level factors, per-component factors, the blended
score, the outcome band, and — importantly — the evidence quality override that
turns a thin-input analysis into "further assessment required" instead of a
confident number.
"""

from __future__ import annotations

from app.rules.suitability_rules import (
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
    version = RULE_PACK_VERSION

    def assess(
        self,
        requirements: ApplicationRequirements,
        signals: RequirementSignals,
        plans: list[ComponentPlan],
    ) -> SuitabilityReport:
        ctx = EvaluationContext(
            requirements=requirements,
            signals=signals,
            spike_factor=self._spike_factor(signals),
            spike_is_assumed=signals.peak_requests_per_minute is None,
        )

        workload_factors = evaluate_workload(ctx)
        workload_score, workload_missing_weight, workload_missing = score_and_gaps(workload_factors)

        scored_plans = [plan for plan in plans if tier_of(plan) in SCORED_TIERS]
        component_results: list[ComponentSuitability] = []
        for plan in scored_plans:
            factors = evaluate_component(
                plan.traits,
                spike_factor=ctx.spike_factor,
                always_on_platform_penalty=plan.traits.always_on and signals.longest_operation_minutes is None,
            )
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
        total_missing_weight = max(workload_missing_weight, _component_missing_weight(scored_plans, ctx))
        outcome, provisional = overall_outcome(combined, total_missing_weight)
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

    @staticmethod
    def _spike_factor(signals: RequirementSignals) -> float:
        """Peak/average factor, derived from stated figures when possible."""
        if signals.monthly_requests and signals.peak_requests_per_minute:
            average = signals.monthly_requests / (26 * 24 * 60)
            if average > 0:
                return round(max(1.0, signals.peak_requests_per_minute / average), 2)
        return 1.35


def tier_of(plan: ComponentPlan) -> ComponentTier:
    from app.services.component_identifier import TIER_BY_TYPE

    return TIER_BY_TYPE[plan.type]


def score_and_gaps(factors: list[FactorResult]) -> tuple[float, float, list[str]]:
    from app.rules.suitability_rules import score_from_factors

    return score_from_factors(factors)


def _component_missing_weight(plans: list[ComponentPlan], ctx: EvaluationContext) -> float:
    if not plans:
        return 0.0
    total = 0.0
    for plan in plans:
        factors = evaluate_component(plan.traits, spike_factor=ctx.spike_factor)
        _, missing_weight, _ = score_and_gaps(factors)
        total += missing_weight
    return round(total / len(plans), 4)


def _bands() -> list[tuple[float, SuitabilityOutcome]]:
    from app.rules.suitability_rules import BANDS

    ordered = sorted(BANDS, key=lambda item: item[0])
    return [(threshold, outcome) for threshold, outcome in ordered]


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
    return SuitabilityService().assess(requirements, signals, plans)
