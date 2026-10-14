"""Regression tests for the suitability engine's decision paths.

These tests pin *representative* outcomes that the current rule pack (2026.10)
produces, plus the complete component trait space.  Values were computed from the
rules themselves and are asserted with a tolerance of 0.05 points, so a change to
a weight, threshold or factor is a deliberate, visible decision rather than a
silent drift.
"""

from __future__ import annotations

import itertools

import pytest

from app.rules.suitability_rules import (
    COMPONENT_FACTOR_WEIGHTS,
    FactorResult,
    band_for,
    component_score_and_outcome,
    evaluate_component,
    recommended_pattern,
)
from app.schemas.architecture import ComponentTraits
from app.schemas.common import (
    ComponentRuntime,
    DeploymentTarget,
    DurationProfile,
    RecommendedPattern,
    SuitabilityOutcome,
)
from app.services.serverless_suitability import SuitabilityService
from tests.test_suitability import assess

TOLERANCE = 0.05

# ---------------------------------------------------------------------------
# Component trait space
# ---------------------------------------------------------------------------

BOOLEAN_TRAITS = (
    "stateful",
    "always_on",
    "event_triggered",
    "persistent_connections",
    "cpu_or_memory_intensive",
    "gpu_required",
    "custom_runtime",
)


def _all_trait_combinations():
    """Every boolean dimension x every runtime x every duration profile."""
    for flags in itertools.product((False, True), repeat=len(BOOLEAN_TRAITS)):
        for runtime in ComponentRuntime:
            for duration in DurationProfile:
                values = dict(zip(BOOLEAN_TRAITS, flags, strict=True))
                yield ComponentTraits(runtime=runtime, duration=duration, **values)


def test_trait_space_covers_every_boolean_dimension_runtime_and_duration():
    combinations = list(_all_trait_combinations())
    expected = 2 ** len(BOOLEAN_TRAITS) * len(ComponentRuntime) * len(DurationProfile)
    assert len(combinations) == expected == 2 ** 7 * 8 * 5
    # Each boolean really varies across the enumeration (guards against a silent no-op).
    for name in BOOLEAN_TRAITS:
        assert {getattr(item, name) for item in combinations} == {False, True}, name


def test_every_component_combination_scores_in_range_with_a_band_verdict():
    """Exhaustive: all 5,120 combinations (7 booleans x 8 runtimes x 5 durations)."""
    checked = 0
    for traits in _all_trait_combinations():
        factors = evaluate_component(traits)
        score, outcome, missing = component_score_and_outcome(factors)
        assert 0.0 <= score <= 100.0, traits
        # Component verdicts are always the score band (see component_score_and_outcome).
        assert outcome is band_for(score), traits
        assert outcome is not SuitabilityOutcome.FURTHER_ASSESSMENT, traits
        assert set(missing) <= {"duration"}, traits
        checked += 1
    assert checked == 2 ** len(BOOLEAN_TRAITS) * len(ComponentRuntime) * len(DurationProfile)


def test_the_component_missing_weight_is_bounded_by_the_duration_weight():
    """The former 0.34 component gate was removed because it could never fire.

    Only `duration` can lack evidence at component level, so the largest possible
    missing weight is that factor's weight.  This test makes that arithmetic explicit.
    """
    largest = max(
        sum(item.weight for item in evaluate_component(traits) if item.basis == "missing")
        for traits in _all_trait_combinations()
    )
    assert largest == pytest.approx(COMPONENT_FACTOR_WEIGHTS["duration"])
    assert largest == pytest.approx(0.26)


def test_component_missing_inputs_are_reported_but_do_not_override_the_band():
    traits = ComponentTraits(runtime=ComponentRuntime.REQUEST_RESPONSE, duration=DurationProfile.UNSPECIFIED)
    factors = evaluate_component(traits)
    score, outcome, missing = component_score_and_outcome(factors)
    assert missing == ["duration"]
    assert outcome is band_for(score)


# ---------------------------------------------------------------------------
# Representative absolute scores (end-to-end, through extraction and identification)
# ---------------------------------------------------------------------------

REPRESENTATIVE = {
    # description: (score, outcome, recommended pattern)
    "A REST API backed by a relational database with 10000 users. Mostly stateless, traffic is spiky during "
    "exam windows, jobs run asynchronously through a queue, availability is high, and the longest operation "
    "finishes in under a minute.": (77.1, SuitabilityOutcome.SUITABLE_WITH_MODIFICATIONS, RecommendedPattern.SERVERLESS_WHERE_SUITABLE),
    "A nightly batch that imports CSV files from partners and writes summaries to a relational database for "
    "200 analysts.": (71.5, SuitabilityOutcome.SUITABLE_WITH_MODIFICATIONS, RecommendedPattern.SERVERLESS_WHERE_SUITABLE),
    "A video transcoding service for 500 creators: uploads are transcoded with ffmpeg, each job runs 40 minutes, "
    "and results are stored in object storage. Traffic is steady.": (48.5, SuitabilityOutcome.PARTIAL_ADOPTION, RecommendedPattern.HYBRID),
}


@pytest.mark.parametrize("description", list(REPRESENTATIVE), ids=["api", "nightly-batch", "transcoding"])
def test_representative_scores_outcomes_and_patterns_are_pinned(description):
    score, outcome, pattern = REPRESENTATIVE[description]
    report = assess(description)
    assert report.score == pytest.approx(score, abs=TOLERANCE)
    assert report.outcome is outcome
    assert report.recommended_pattern is pattern
    assert report.provisional_score is None


def test_fully_evidenced_long_stateful_workload_reaches_managed_container():
    """Real end-to-end path: poor verdict + long-running work -> managed container."""
    report = assess(
        "A video rendering service for 500 editors: each render job runs for 90 minutes, holds in-memory state "
        "for the whole job, needs a persistent websocket connection for progress, uses ffmpeg with GPU "
        "acceleration, traffic is steady and availability is high.",
        availability="high",
    )
    assert report.score == pytest.approx(36.2, abs=TOLERANCE)
    assert report.outcome is SuitabilityOutcome.POOR_CANDIDATE
    assert report.recommended_pattern is RecommendedPattern.MANAGED_CONTAINER
    container_components = [item for item in report.components if item.recommendation is DeploymentTarget.CONTAINER]
    assert container_components, "long-running and connection-bound components must land on containers"


def test_provisional_workload_is_flagged_and_not_quoted_as_a_verdict():
    report = assess("A new internal tool for a few people that the team has not described in detail yet.")
    assert report.outcome is SuitabilityOutcome.FURTHER_ASSESSMENT
    assert report.provisional_score is not None
    assert report.recommended_pattern is RecommendedPattern.FURTHER_ASSESSMENT


# ---------------------------------------------------------------------------
# Decision table for recommended_pattern (every branch)
# ---------------------------------------------------------------------------


def _factor(factor_id: str, impact: float) -> FactorResult:
    return FactorResult(id=factor_id, name=factor_id, weight=0.1, impact=impact, explanation="test", basis="inferred")


SERVERLESS = {"c": DeploymentTarget.SERVERLESS_FUNCTION}
MIXED = {"c": DeploymentTarget.SERVERLESS_FUNCTION, "b": DeploymentTarget.CONTAINER}
NO_SERVERLESS = {"c": DeploymentTarget.CONTAINER}
NEUTRAL = [_factor("execution_duration", 0.2), _factor("resource_intensity", 0.0)]
LONG = [_factor("execution_duration", -0.8), _factor("resource_intensity", 0.0)]
HEAVY = [_factor("execution_duration", 0.2), _factor("resource_intensity", -0.7)]


@pytest.mark.parametrize(
    ("outcome", "factors", "targets", "expected"),
    [
        (SuitabilityOutcome.FURTHER_ASSESSMENT, NEUTRAL, SERVERLESS, RecommendedPattern.FURTHER_ASSESSMENT),
        (SuitabilityOutcome.STRONG_CANDIDATE, NEUTRAL, SERVERLESS, RecommendedPattern.SERVERLESS_FIRST),
        (SuitabilityOutcome.SUITABLE_WITH_MODIFICATIONS, NEUTRAL, MIXED, RecommendedPattern.HYBRID),
        (SuitabilityOutcome.SUITABLE_WITH_MODIFICATIONS, NEUTRAL, SERVERLESS, RecommendedPattern.SERVERLESS_WHERE_SUITABLE),
        (SuitabilityOutcome.PARTIAL_ADOPTION, NEUTRAL, MIXED, RecommendedPattern.HYBRID),
        (SuitabilityOutcome.POOR_CANDIDATE, LONG, NO_SERVERLESS, RecommendedPattern.MANAGED_CONTAINER),
        (SuitabilityOutcome.POOR_CANDIDATE, HEAVY, NO_SERVERLESS, RecommendedPattern.MANAGED_CONTAINER),
        (SuitabilityOutcome.POOR_CANDIDATE, NEUTRAL, NO_SERVERLESS, RecommendedPattern.CONVENTIONAL_KEEP),
    ],
)
def test_recommended_pattern_decision_table(outcome, factors, targets, expected):
    assert recommended_pattern(outcome, factors, targets) is expected


def test_the_spike_factor_default_is_reported_as_an_assumption():
    from app.schemas.requirements import RequirementSignals

    assert SuitabilityService._spike_factor(RequirementSignals()) == pytest.approx(1.35)
    stated = RequirementSignals(monthly_requests=26 * 24 * 60 * 2, peak_requests_per_minute=8)
    # Average is 2 requests/minute (monthly figure spread over 26 business days), peak is 8: a 4x ratio.
    assert SuitabilityService._spike_factor(stated) == pytest.approx(4.0)
