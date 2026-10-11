"""Serverless suitability scoring: deterministic, evidence-based, explainable."""

from __future__ import annotations

import math

import pytest

from app.rules.suitability_rules import (
    BANDS,
    COMPONENT_FACTOR_WEIGHTS,
    MISSING_WEIGHT_LIMIT,
    WORKLOAD_FACTORS,
    aggregate_score,
    band_for,
    overall_outcome,
)
from app.schemas.common import AvailabilityExpectation, DeploymentTarget, RecommendedPattern, SuitabilityOutcome, TrafficPattern
from app.schemas.requirements import ApplicationRequirements
from app.services.component_identifier import identify
from app.services.requirement_extractor import extract_requirements
from app.services.serverless_suitability import SuitabilityService
from app.services.templates import requirements_for

SERVICE = SuitabilityService()


def assess(description: str, **overrides):
    """Run the same hand-off the pipeline uses: extraction enriches the
    requirement document, and scoring reads that enriched copy."""
    payload = {"name": "Suitability fixture", "description": description}
    payload.update(overrides)
    requirements = ApplicationRequirements(**payload)
    extraction = extract_requirements(requirements)
    plans, _inventory = identify(extraction.requirements, extraction.signals)
    return SERVICE.assess(extraction.requirements, extraction.signals, plans)


def workload_score(report) -> float:
    return min(100.0, max(0.0, 100.0 * (0.5 + 0.5 * sum(f.weight * f.impact for f in report.factors))))


def _favourable(text: str, **overrides):
    """The favourable fixture states availability explicitly: the engine refuses to
    infer an SLO from silence, and that is exactly the behaviour under test."""
    return assess(text, availability="high", **overrides)


RICH = (
    "A REST API backed by a relational database with 10000 users. Mostly stateless, traffic is spiky during "
    "exam windows, jobs run asynchronously through a queue, availability is high, and the longest operation "
    "finishes in under a minute."
)


def test_every_factor_has_a_weight_and_the_weights_sum_to_one():
    assert len(WORKLOAD_FACTORS) >= 10
    assert abs(sum(factor.weight for factor in WORKLOAD_FACTORS) - 1.0) < 1e-9
    for factor in WORKLOAD_FACTORS:
        assert 0 < factor.weight <= 0.2, factor.id
        assert factor.name
    assert 0 < sum(COMPONENT_FACTOR_WEIGHTS.values()) <= 1.0 + 1e-9


def test_score_follows_the_published_methodology():
    report = assess(RICH)
    expected = aggregate_score(workload_score(report), [component.score for component in report.components])
    if report.provisional_score is None:
        assert report.score == pytest.approx(expected, abs=0.15)
    else:
        assert report.score == pytest.approx(workload_score(report), abs=0.15)
        assert report.provisional_score == pytest.approx(expected, abs=0.15)
    assert "score = 100 x (0.5 + 0.5 x" in report.methodology.formula


def test_every_factor_is_explained_and_evidenced():
    report = assess(RICH)
    assert len(report.factors) == len(WORKLOAD_FACTORS)
    for factor in report.factors:
        assert factor.name and factor.explanation
        assert factor.evidence, f"{factor.id} has no evidence trail"
        assert factor.basis in {"user_provided", "inferred", "default", "missing"}
        assert -1.0 <= factor.impact <= 1.0
        assert math.isclose(factor.contribution, factor.weight * factor.impact, abs_tol=1e-6)
        assert factor.direction in {"positive", "negative", "neutral"}
        if factor.impact > 0.15:
            assert factor.direction == "positive", factor.id
        elif factor.impact < -0.15:
            assert factor.direction == "negative", factor.id
        else:
            assert factor.direction == "neutral", f"{factor.id} leaned on a near-zero impact"


def test_favourable_evidence_raises_the_score_and_contradictions_lower_it():
    base = assess(RICH)
    favourable = _favourable(
        "A stateless REST API for 1000000 users with extremely spiky event-driven traffic. Every request "
        "finishes in milliseconds, all heavy work runs asynchronously through queues, and the database is "
        "reached through a connection proxy. Weekends are idle."
    )
    unfavourable = assess(
        "A stateless REST API for 50 users. Sessions live in process memory, websocket connections stay open "
        "indefinitely, each job runs for nine hours on a GPU with a custom runtime, and the service must stay "
        "warm with no cold starts at all."
    )
    assert unfavourable.score < base.score < favourable.score
    assert favourable.outcome is SuitabilityOutcome.STRONG_CANDIDATE
    assert favourable.score >= 78.0
    assert unfavourable.score <= base.score - 10
    assert unfavourable.outcome in {
        SuitabilityOutcome.FURTHER_ASSESSMENT,
        SuitabilityOutcome.PARTIAL_ADOPTION,
        SuitabilityOutcome.POOR_CANDIDATE,
    }


def test_unknowns_are_never_counted_as_favourable_and_are_listed_once():
    report = assess("An internal application for 40 staff members.")
    missing = [factor for factor in report.factors if factor.basis == "missing"]
    assert missing, "an input with almost no evidence should leave factors unscored"
    for factor in missing:
        assert factor.impact == 0.0
        assert factor.contribution == 0.0
        assert factor.evidence == ["No supporting statement in the inputs."] or "not" in factor.explanation.lower()
    for label in report.missing_inputs:
        assert report.missing_inputs.count(label) == 1, f"{label!r} listed more than once"


def test_heavy_missing_evidence_forces_further_assessment():
    report = assess("We have an application that does some processing.")
    missing_weight = sum(factor.weight for factor in report.factors if factor.basis == "missing")
    assert missing_weight >= MISSING_WEIGHT_LIMIT
    assert report.outcome is SuitabilityOutcome.FURTHER_ASSESSMENT
    assert report.provisional_score is not None
    assert report.caveats and any("%" in caveat for caveat in report.caveats)
    outcome, provisional = overall_outcome(report.score, missing_weight)
    assert (outcome, provisional) == (report.outcome, True)


def test_band_boundaries_are_ordered_and_monotonic():
    thresholds = [minimum for minimum, _ in BANDS]
    assert thresholds == sorted(thresholds, reverse=True)
    assert thresholds[0] > thresholds[-1] == 0.0
    for minimum, outcome in BANDS:
        assert band_for(minimum) is outcome
        assert band_for(minimum + 0.01) is outcome
        assert band_for(minimum - 0.01) is not outcome or minimum == 0.0
    for score in (0.0, 12.0, 50.0, 63.0, 79.0, 100.0):
        assert band_for(score) in set(SuitabilityOutcome)


def test_outcome_matches_the_band_when_evidence_is_complete():
    report = assess(RICH)
    if report.provisional_score is None:
        assert report.outcome is band_for(report.score)


def test_hybrid_recommendation_moves_long_running_work_onto_containers():
    report = assess(
        "A web application with a stateless API tier, a relational database and video transcoding jobs that run "
        "for 40 minutes on a GPU. 3000 users, spiky traffic during evening peaks, availability standard."
    )
    assert report.recommended_pattern is RecommendedPattern.HYBRID
    targets = {component.recommendation for component in report.components}
    assert DeploymentTarget.CONTAINER in targets
    long_running = [
        component
        for component in report.components
        if component.recommendation is DeploymentTarget.CONTAINER
    ]
    assert long_running
    for component in long_running:
        assert component.recommendation_reason
        assert (component.reasons_for or component.reasons_against), "a component verdict needs visible reasons"
        assert component.factors
        assert 0 <= component.score <= 100


def test_always_on_and_stateful_components_are_not_labelled_functions():
    report = assess(
        "A realtime collaboration backend that keeps websocket connections open for hours, stores the session "
        "in process memory and always runs, with 200000 concurrent users."
    )
    assert report.components
    for component in report.components:
        if component.recommendation is DeploymentTarget.SERVERLESS_FUNCTION:
            assert component.score >= 62.0, "a low-scoring component must not be pushed onto the function runtime"


def test_managed_data_components_are_excluded_from_the_component_average():
    report = assess(RICH)
    ids = {component.component_id for component in report.components}
    assert ids, "some components must be scored"
    for component in report.components:
        assert component.component_label
        assert component.outcome in set(SuitabilityOutcome)
        assert isinstance(component.provisional, bool)


def test_stated_enum_inputs_are_used_directly():
    report = assess(
        "A stateless REST API with a relational database and asynchronous processing.",
        expected_users=50_000,
        traffic_pattern=TrafficPattern.SPIKY_EVENT,
        availability=AvailabilityExpectation.CRITICAL,
    )
    by_id = {factor.id: factor for factor in report.factors}
    assert by_id["traffic_variability"].impact > 0
    assert by_id["traffic_variability"].basis == "user_provided", "a stated enum must not be called inferred"
    assert any("spiky" in evidence.lower() for evidence in by_id["traffic_variability"].evidence)
    assert by_id["availability_requirement"].basis == "user_provided"
    assert by_id["availability_requirement"].impact < 0, "a critical SLO is a constraint, not a bonus"


def test_identical_input_produces_identical_output():
    assert assess(RICH).model_dump() == assess(RICH).model_dump()


@pytest.mark.parametrize(
    "identifier",
    [
        "college-attendance",
        "online-examination",
        "ecommerce-application",
        "food-delivery-platform",
        "file-processing-pipeline",
    ],
)
def test_templates_produce_distinct_defensible_verdicts(identifier):
    report = assess(requirements_for(identifier).description)
    assert 0.0 <= report.score <= 100.0
    assert report.outcome in set(SuitabilityOutcome)
    assert report.headline
    assert report.rationale
    assert report.caveats
    assert report.methodology.bands


def test_file_processing_template_is_honest_about_not_knowing_enough():
    requirements = requirements_for("file-processing-pipeline")
    extraction = extract_requirements(requirements)
    plans, _ = identify(extraction.requirements, extraction.signals)
    report = SERVICE.assess(extraction.requirements, extraction.signals, plans)
    assert report.missing_inputs
    assert report.outcome in {SuitabilityOutcome.FURTHER_ASSESSMENT, SuitabilityOutcome.PARTIAL_ADOPTION}
