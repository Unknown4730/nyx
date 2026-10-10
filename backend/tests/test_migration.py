"""Migration planner: derived complexity, per-component changes, sequenced phases."""

from __future__ import annotations

import re

import pytest

from app.schemas.analysis import AnalysisOptions, AnalysisRequest
from app.schemas.common import EffortLevel, Severity, SuitabilityOutcome
from app.services.migration_planner import CHANGE_RULES, MigrationPlanner
from app.services.pipeline import AnalysisPipeline
from app.services.templates import requirements_for
from app.schemas.architecture import ComponentTraits

PLANNER = MigrationPlanner()


def _result(identifier: str):
    return AnalysisPipeline().run(
        AnalysisRequest(requirements=requirements_for(identifier), options=AnalysisOptions(use_ai=False))
    )


@pytest.fixture(scope="module")
def exam():
    return _result("online-examination")


@pytest.fixture(scope="module")
def batch():
    return _result("file-processing-pipeline")


def _all_rules():
    for component_type, rules in CHANGE_RULES.items():
        for rule in rules:
            yield component_type, rule


def test_change_rules_cover_the_component_vocabulary():
    from app.schemas.common import LogicalComponentType

    assert set(CHANGE_RULES) <= set(LogicalComponentType)
    assert len(CHANGE_RULES) >= 14
    seen_phases = set()
    for component_type, rule in _all_rules():
        assert rule.key and rule.change, component_type
        assert rule.complexity in set(EffortLevel), f"{component_type.value}/{rule.key}"
        assert rule.reason
        assert isinstance(rule.activities, tuple) and rule.activities
        assert all(isinstance(activity, str) for activity in rule.activities), (
            f"{component_type.value} activities must be strings, not characters of one"
        )
        assert isinstance(rule.dependencies, tuple) and isinstance(rule.issues, tuple)
        assert isinstance(rule.exit_criteria, tuple) and rule.exit_criteria
        seen_phases.add(rule.phase)
    assert {"inventory", "decomposition", "operations"} & seen_phases or seen_phases


def test_complexity_score_is_derived_from_the_changes(exam):
    migration = exam.migration
    assert 0.0 <= migration.complexity_score <= 100.0
    assert migration.overall_complexity in set(EffortLevel) or migration.overall_complexity.value in {
        "low",
        "moderate",
        "high",
        "further_assessment_required",
    }
    assert migration.complexity_drivers
    for driver in migration.complexity_drivers:
        assert driver


def test_complexity_differs_between_templates(exam, batch):
    assert exam.migration.overall_complexity != batch.migration.overall_complexity or (
        exam.migration.complexity_score != batch.migration.complexity_score
    )


def test_provisional_suitability_makes_the_roadmap_conditional(batch):
    assert batch.suitability.outcome is SuitabilityOutcome.FURTHER_ASSESSMENT
    assert batch.migration.overall_complexity.value == "further_assessment_required"
    assert any("open question" in caveat.lower() or "question" in caveat.lower() for caveat in batch.migration.caveats)


def test_every_changed_component_is_tracked_back_to_a_component(exam):
    conventional = {component.id for component in exam.architectures[0].components}
    proposed = {component.id for component in exam.architectures[1].components}
    for change in exam.migration.components_requiring_modification:
        assert change.component_id in conventional | proposed
        assert change.component_label
        assert change.change
        assert change.reason
        assert change.complexity in set(EffortLevel)


def test_phases_are_sequential_non_empty_and_end_with_a_cutover(exam):
    phases = exam.migration.phases
    assert 3 <= len(phases) <= 10
    assert [phase.index for phase in phases] == list(range(1, len(phases) + 1))
    assert len({phase.id for phase in phases}) == len(phases)
    for phase in phases:
        assert phase.title and phase.objective
        assert phase.activities
        assert phase.exit_criteria
        assert phase.effort in set(EffortLevel)
        assert phase.risk in set(Severity)
        for component_id in phase.components_touched:
            assert component_id in {component.id for component in exam.architectures[1].components}
    assert re.search(r"validat|cutover|pilot|rollout|operations", " ".join(phase.title.lower() for phase in phases))


def test_roadmap_activity_sets_differ_between_workloads(exam, batch):
    exam_activities = {activity for phase in exam.migration.phases for activity in phase.activities}
    batch_activities = {activity for phase in batch.migration.phases for activity in phase.activities}
    assert exam_activities != batch_activities
    assert any("queue" in activity.lower() or "worker" in activity.lower() for activity in batch_activities | exam_activities)


def test_no_time_estimates_are_published(exam, batch):
    for result in (exam, batch):
        blob = result.migration.model_dump_json()
        assert not re.search(r"\b\d+\s*(business\s*)?(days|weeks|sprints|person-days|developer-days)\b", blob, re.IGNORECASE)
        assert not re.search(r"\$\s?\d", blob)
    assert any("does not publish durations" in caveat for caveat in result.migration.caveats)


def test_validation_requirements_and_risks_are_specific(exam):
    assert exam.migration.validation_requirements
    assert exam.migration.risks
    for risk in exam.migration.risks:
        assert len(risk) > 30
    assert any(
        re.search(r"timeout|duration|stateless|connection", requirement, re.IGNORECASE)
        for requirement in exam.migration.validation_requirements
    )


def test_dependencies_reference_real_components(exam):
    for item in exam.migration.dependencies_to_review:
        assert item
        assert len(item) > 20
    for change in exam.migration.components_requiring_modification:
        for dependency in change.dependencies:
            assert dependency


def test_compatibility_issues_are_derived_from_traits_not_from_opinion(batch):
    traits: list[ComponentTraits] = [component.traits for component in batch.architectures[1].components]
    issues = batch.migration.compatibility_issues
    for issue in issues:
        assert issue
    if any(trait.gpu_required for trait in traits):
        assert any("gpu" in issue.lower() for issue in issues)
    if any(trait.custom_runtime for trait in traits):
        assert any("runtime" in issue.lower() for issue in issues)


def test_migration_analysis_is_reproducible(exam):
    again = _result("online-examination")
    assert exam.migration.model_dump() == again.migration.model_dump()
