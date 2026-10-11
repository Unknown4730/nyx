"""Deterministic tests for the authoritative serverless suitability engine.

These tests pin the *contract* of `app.services.serverless_suitability` — the one
module allowed to compose a suitability verdict — rather than any particular
workload's opinion.  They deliberately avoid the cloud catalogue and the template
library so they run in an environment without those data assets.

Nothing here is time- or random-dependent, so every expectation is a literal.
"""

from __future__ import annotations

import ast
import itertools
from pathlib import Path

import pytest

from app.rules.suitability_rules import (
    BAND_DESCRIPTIONS,
    BANDS,
    COMPONENT_FACTOR_WEIGHTS,
    COMPONENT_MISSING_WEIGHT_LIMIT,
    MISSING_WEIGHT_LIMIT,
    RULE_PACK_VERSION,
    WORKLOAD_FACTORS,
    aggregate_score,
    evaluate_component,
)
from app.schemas.architecture import ComponentTraits
from app.schemas.common import RecommendedPattern, SuitabilityOutcome
from app.schemas.requirements import ApplicationRequirements
from app.services.component_identifier import identify
from app.services.requirement_extractor import extract_requirements
from app.services.serverless_suitability import (
    SCORED_TIERS,
    SuitabilityService,
    evaluate_suitability,
    report_from_service,
    tier_of,
)

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


# --------------------------------------------------------------------------
# fixtures: hand-written descriptions only, no templates, no catalogue
# --------------------------------------------------------------------------

STRONG = (
    "A stateless REST API for 1000000 users with extremely spiky event-driven traffic. "
    "Every request finishes in milliseconds, all heavy work runs asynchronously through "
    "queues, and the database is reached through a connection proxy. Weekends are idle."
)
RICH = (
    "A REST API backed by a relational database with 10000 users. Mostly stateless, traffic is spiky during "
    "exam windows, jobs run asynchronously through a queue, availability is high, and the longest operation "
    "finishes in under a minute."
)
POOR = (
    "A stateless REST API for 50 users. Sessions live in process memory, websocket connections stay open "
    "indefinitely, each job runs for nine hours on a GPU with a custom runtime, and the service must stay "
    "warm with no cold starts at all."
)
BATCH = (
    "A nightly batch pipeline that reads uploaded CSV files from object storage, transforms them for "
    "25 minutes and writes results to a warehouse. 200 internal users, unpredictable usage."
)
SPARSE = "An internal application for 40 staff members."


def _prepare(description: str, **overrides):
    """Extraction -> identification, exactly the hand-off the pipeline performs."""
    payload = {"name": "Engine fixture", "description": description}
    payload.update(overrides)
    extraction = extract_requirements(ApplicationRequirements(**payload))
    plans, _inventory = identify(extraction.requirements, extraction.signals)
    return extraction.requirements, extraction.signals, plans


def evaluate(description: str, **overrides):
    requirements, signals, plans = _prepare(description, **overrides)
    return evaluate_suitability(requirements, signals, plans)


def workload_score(report) -> float:
    """Recompute the workload score from the published factors, independently."""
    total = sum(factor.weight * factor.impact for factor in report.factors)
    return round(max(0.0, min(100.0, 100.0 * (0.5 + 0.5 * total))), 1)


# --------------------------------------------------------------------------
# 1. there is exactly one engine
# --------------------------------------------------------------------------


def test_there_is_one_authoritative_engine_and_one_rule_pack_version():
    """All three entry points delegate to one implementation, and the rule-pack
    version literal is assigned in exactly one place in the backend."""
    requirements, signals, plans = _prepare(RICH, availability="high")

    authoritative = evaluate_suitability(requirements, signals, plans).model_dump()
    assert SuitabilityService().assess(requirements, signals, plans).model_dump() == authoritative
    assert report_from_service(requirements, signals, plans).model_dump() == authoritative
    # a shared instance behaves identically to a fresh one: no per-call state
    shared = SuitabilityService()
    assert shared.assess(requirements, signals, plans).model_dump() == authoritative
    assert shared.assess(requirements, signals, plans).model_dump() == authoritative

    assignments = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "RULE_PACK_VERSION":
                    assignments.append(path.relative_to(APP_ROOT).as_posix())
    assert assignments == ["rules/suitability_rules.py"], assignments


# --------------------------------------------------------------------------
# 2. determinism
# --------------------------------------------------------------------------


def test_equivalent_normalized_inputs_produce_identical_reports():
    requirements, signals, plans = _prepare(RICH, availability="high")

    first = evaluate_suitability(requirements, signals, plans).model_dump(mode="json")
    for _ in range(50):
        assert evaluate_suitability(requirements, signals, plans).model_dump(mode="json") == first

    # a separately constructed but equivalent request reaches the same verdict
    other_requirements, other_signals, other_plans = _prepare(RICH, availability="high")
    assert (other_requirements, other_signals) == (requirements, signals)
    assert evaluate_suitability(other_requirements, other_signals, other_plans).model_dump(mode="json") == first

    # the iterable form makes no difference
    assert evaluate_suitability(requirements, signals, tuple(plans)).model_dump(mode="json") == first
    assert evaluate_suitability(requirements, signals, iter(plans)).model_dump(mode="json") == first


# --------------------------------------------------------------------------
# 3-4. the arithmetic is exactly the published methodology
# --------------------------------------------------------------------------


@pytest.mark.parametrize("description", [STRONG, RICH, POOR, BATCH, SPARSE])
def test_every_factor_is_weighted_evidenced_and_within_the_published_scale(description):
    report = evaluate(description, availability="high")

    assert [factor.id for factor in report.factors] == [factor.id for factor in WORKLOAD_FACTORS]
    assert abs(sum(factor.weight for factor in report.factors) - 1.0) < 1e-9
    for factor in report.factors:
        assert -1.0 <= factor.impact <= 1.0, factor.id
        assert factor.contribution == pytest.approx(factor.weight * factor.impact, abs=1e-6), factor.id
        assert factor.basis in {"user_provided", "inferred", "default", "missing"}, factor.basis
        assert factor.explanation, factor.id
    assert 0.0 <= report.score <= 100.0


@pytest.mark.parametrize("description", [STRONG, RICH, POOR, BATCH, SPARSE])
def test_blended_score_is_the_published_55_45_blend_of_workload_and_components(description):
    report = evaluate(description, availability="high")
    expected = aggregate_score(workload_score(report), [item.score for item in report.components])

    if report.provisional_score is None:
        assert report.score == pytest.approx(expected, abs=0.15)
    else:
        assert report.score == pytest.approx(workload_score(report), abs=0.15)
        assert report.provisional_score == pytest.approx(expected, abs=0.15)
    assert "score = 100 x (0.5 + 0.5 x" in report.methodology.formula


# --------------------------------------------------------------------------
# 5-6. missing evidence is explicit, never defaulted to favourable
# --------------------------------------------------------------------------


def test_missing_evidence_contributes_zero_and_is_disclosed():
    report = evaluate(SPARSE)
    missing = [factor for factor in report.factors if factor.basis == "missing"]

    assert missing, "a one-line description must leave factors without evidence"
    for factor in missing:
        assert factor.impact == 0.0, f"{factor.id} was defaulted to a value instead of reported as unknown"
        assert factor.contribution == 0.0, factor.id
        assert factor.name in report.missing_inputs

    # a richly described workload still cannot invent evidence it was not given,
    # but it is left with strictly less unknown weight than the one-liner
    rich_missing = [factor for factor in evaluate(RICH, availability="high").factors if factor.basis == "missing"]
    assert len(rich_missing) < len(missing)
    for factor in rich_missing:
        assert factor.impact == 0.0, factor.id
        assert factor.name in evaluate(RICH, availability="high").missing_inputs


def test_thin_evidence_downgrades_the_verdict_instead_of_publishing_a_number():
    report = evaluate(SPARSE)

    assert report.outcome == SuitabilityOutcome.FURTHER_ASSESSMENT
    assert report.provisional_score is not None
    assert report.score == pytest.approx(workload_score(report), abs=0.15)
    assert any("provisional" in caveat for caveat in report.caveats)
    assert report.recommended_pattern == RecommendedPattern.FURTHER_ASSESSMENT


# --------------------------------------------------------------------------
# 7-8. the engine can say no, and can say hybrid
# --------------------------------------------------------------------------


def test_an_unsuitable_workload_is_not_labelled_serverless_friendly():
    report = evaluate(POOR)

    assert report.outcome not in {
        SuitabilityOutcome.STRONG_CANDIDATE,
        SuitabilityOutcome.SUITABLE_WITH_MODIFICATIONS,
    }
    assert report.recommended_pattern != RecommendedPattern.SERVERLESS_FIRST
    assert report.concerns, "an unsuitable workload must state why"
    assert report.score < 62.0


def test_a_hybrid_recommendation_is_reachable_and_component_aware():
    report = evaluate(BATCH)

    assert report.recommended_pattern == RecommendedPattern.HYBRID
    recommendations = {item.recommendation.value for item in report.components}
    assert len(report.components) > 1
    assert "serverless_function" in recommendations
    assert "container" in recommendations
    for item in report.components:
        assert item.recommendation_reason


# --------------------------------------------------------------------------
# 9-10. the methodology block is published and self-consistent
# --------------------------------------------------------------------------


def test_published_bands_are_exhaustive_monotonic_and_taken_from_the_rule_pack():
    report = evaluate(RICH, availability="high")
    published = report.methodology.bands

    thresholds = [band.min_score for band in published]
    assert thresholds == sorted(thresholds), "methodology.bands must read as an ascending ladder"
    assert thresholds[0] == 0.0 and thresholds[-1] == max(threshold for threshold, _ in BANDS)
    assert [(band.min_score, band.outcome) for band in published] == sorted(BANDS, key=lambda item: item[0])
    for band in published:
        assert band.description == BAND_DESCRIPTIONS[band.outcome]


def test_methodology_names_the_rule_pack_version_and_the_evidence_gate():
    report = evaluate(RICH, availability="high")
    methodology = report.methodology

    assert methodology.formula and methodology.weight_source and methodology.notes
    assert RULE_PACK_VERSION in methodology.band_source
    assert f"{MISSING_WEIGHT_LIMIT:.0%}" in " ".join(methodology.notes)
    assert SuitabilityService.version == RULE_PACK_VERSION


# --------------------------------------------------------------------------
# 11. only genuine compute decisions are scored
# --------------------------------------------------------------------------


def test_only_application_and_processing_components_are_scored():
    _requirements, _signals, plans = _prepare(POOR)
    report = evaluate(POOR)

    scored_ids = {item.component_id for item in report.components}
    expected = {plan.id or plan.type.value for plan in plans if tier_of(plan) in SCORED_TIERS}
    assert scored_ids == expected
    assert len(plans) > len(report.components), "managed rails must be excluded, not scored as functions"
    for plan in plans:
        if plan.id in scored_ids:
            assert tier_of(plan) in SCORED_TIERS


# --------------------------------------------------------------------------
# 12. malformed input fails loudly
# --------------------------------------------------------------------------


def test_malformed_input_is_rejected_rather_than_scored():
    requirements, signals, plans = _prepare(RICH, availability="high")
    good = evaluate_suitability(requirements, signals, plans).model_dump()

    cases = [
        ("not-a-requirements", signals, plans),
        (requirements, "not-signals", plans),
        (requirements, signals, "not-an-iterable"),
        (requirements, signals, 42),
        (requirements, signals, [object()]),
    ]
    for arguments in cases:
        with pytest.raises(TypeError):
            evaluate_suitability(*arguments)

    # rejecting bad input must not have damaged the engine
    assert evaluate_suitability(requirements, signals, plans).model_dump() == good


# --------------------------------------------------------------------------
# 13. the evidence gates are the documented values, not arbitrary constants
# --------------------------------------------------------------------------


def test_evidence_gates_keep_their_documented_values_and_the_component_gate_is_known_to_be_dormant():
    assert MISSING_WEIGHT_LIMIT == 0.30
    assert COMPONENT_MISSING_WEIGHT_LIMIT == 0.34
    assert COMPONENT_FACTOR_WEIGHTS["duration"] == 0.26

    # `duration` is the only component factor that can ever be reported missing, so
    # the component-level gate cannot currently fire.  That is a documented
    # limitation, not a bug to be silently "fixed": lowering the threshold would
    # reclassify published component outcomes and is an unapproved breaking change.
    # See docs/backend/SUITABILITY_ENGINE.md -> "Known limitations".  This loop
    # proves the claim instead of asserting it from memory.
    enum_fields = {
        name: list(field.annotation.__members__.values())
        for name, field in ComponentTraits.model_fields.items()
        if hasattr(field.annotation, "__members__")
    }
    assert enum_fields, "expected ComponentTraits to expose enum-typed fields"

    worst = 0.0
    missing_ids: set[str] = set()
    evaluated = 0
    for combination in itertools.product(*enum_fields.values()):
        traits = ComponentTraits(**dict(zip(enum_fields, combination)))
        for penalty in (False, True):
            for spike_factor in (1.0, 1.35, 8.0):
                factors = evaluate_component(
                    traits, spike_factor=spike_factor, always_on_platform_penalty=penalty
                )
                evaluated += 1
                missing = [factor for factor in factors if factor.basis == "missing"]
                missing_ids.update(factor.id for factor in missing)
                worst = max(worst, round(sum(factor.weight for factor in missing), 6))

    assert evaluated == 240, "the trait space must be swept exhaustively"
    assert missing_ids == {"duration"}
    assert worst == COMPONENT_FACTOR_WEIGHTS["duration"]
    assert worst < COMPONENT_MISSING_WEIGHT_LIMIT, "the component gate is documented as dormant"
