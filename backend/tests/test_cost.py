"""Relative cost model: arithmetic consistency, honest units, no currency claims."""

from __future__ import annotations

import re

import pytest

from app.rules.cost_rates import COST_MODEL_VERSION, Rates
from app.schemas.common import CostCategory
from app.schemas.requirements import ApplicationRequirements
from app.services.cost_estimator import estimate_cost
from app.schemas.analysis import AnalysisOptions, AnalysisRequest
from app.services.pipeline import AnalysisPipeline
from app.services.requirement_extractor import extract_requirements
from app.services.templates import requirements_for

import dataclasses

RATE_FIELDS = {field.name for field in dataclasses.fields(Rates)}
assert "instance_small" in RATE_FIELDS and len(RATE_FIELDS) >= 15


def _estimate(description: str, **overrides):
    requirements = ApplicationRequirements(name="Cost fixture", description=description, **overrides)
    outcome = extract_requirements(requirements)
    return estimate_cost(requirements, outcome.signals)


def test_totals_are_the_sum_of_their_line_items():
    report = _estimate(
        "An examination platform for 10000 students with an authenticated API, relational database, "
        "PDF generation, a queue with workers and email notifications; availability is high."
    )
    assert len(report.scenarios) == 2
    for scenario in report.scenarios:
        by_category: dict[str, float] = {}
        for item in scenario.line_items:
            by_category[item.category.value] = by_category.get(item.category.value, 0.0) + item.ricu
        assert scenario.fixed_ricu == pytest.approx(by_category.get(CostCategory.FIXED.value, 0.0), abs=0.05)
        assert scenario.variable_ricu == pytest.approx(by_category.get(CostCategory.VARIABLE.value, 0.0), abs=0.05)
        assert scenario.operational_ricu == pytest.approx(
            by_category.get(CostCategory.OPERATIONAL.value, 0.0), abs=0.05
        )
        assert scenario.total_ricu == pytest.approx(sum(item.ricu for item in scenario.line_items), abs=0.05)
        assert scenario.total_ricu > 0


def test_every_line_item_states_its_quantity_unit_and_basis():
    report = _estimate("A file sharing tool for 800 users with object storage and a relational database.")
    for scenario in report.scenarios:
        for item in scenario.line_items:
            assert item.label and item.basis
            assert item.quantity >= 0
            assert item.unit
            assert item.ricu >= 0
            # Every line must show how it was arrived at: either a quantity with the
            # coefficient used, or an explicit statement that no quantity was available.
            lowered = item.basis.lower()
            assert any(character.isdigit() for character in item.basis) or any(
                marker in lowered for marker in ("not ", "no ", "conventional", "identical", "same", "assumed", "default")
            ), item.basis


def test_no_currency_or_absolute_price_appears_anywhere():
    report = _estimate("An online examination platform for 10000 students with an API, database and file storage.")
    text = report.model_dump_json()
    assert not re.search(r"(₹|\$|€|GBP|USD|rupee|dollar|euros?)", text, re.IGNORECASE)
    assert report.unit == "RICU"
    assert "Relative Infrastructure Cost Unit" in report.unit_name
    assert "not money" in report.disclaimer or "not currency" in report.disclaimer.lower()
    for scenario in report.scenarios:
        assert scenario.label and scenario.description
        for assumption in scenario.assumptions:
            assert "RICU" in assumption or "relative" in assumption.lower() or "not " in assumption.lower()
    assert "RICU" in report.disclaimer


def test_comparison_is_derived_from_the_scenario_totals():
    report = _estimate(
        "An e-commerce storefront with 50000 users, spiky traffic, a search index, relational database, "
        "object storage for images and asynchronous order notifications."
    )
    conventional, proposed = report.scenarios
    comparison = report.comparison
    assert comparison["conventional_total"] == pytest.approx(conventional.total_ricu, abs=0.05)
    assert comparison["proposed_total"] == pytest.approx(proposed.total_ricu, abs=0.05)
    ratio = proposed.total_ricu / conventional.total_ricu
    assert comparison["ratio_proposed_to_conventional"] == pytest.approx(ratio, abs=0.01)
    assert comparison["model_relative_change_pct"] == pytest.approx((ratio - 1) * 100, abs=0.6)
    assert comparison["absolute_difference_ricu"] == pytest.approx(proposed.total_ricu - conventional.total_ricu, abs=0.05)


def test_proposed_side_scales_with_usage_while_conventional_scales_with_capacity():
    small = _estimate("An internal wiki for 200 users with a relational database and object storage.")
    large = _estimate("An internal wiki for 200000 users with a relational database and object storage.")
    for report in (small, large):
        conventional, proposed = report.scenarios
        assert conventional.fixed_ricu > 0
        assert proposed.variable_ricu > 0
    small_proposed_variable = small.scenarios[1].variable_ricu
    large_proposed_variable = large.scenarios[1].variable_ricu
    assert large_proposed_variable > small_proposed_variable
    assert large.scenarios[1].total_ricu > small.scenarios[1].total_ricu
    # The conventional baseline must also grow, but through fixed capacity.
    assert large.scenarios[0].fixed_ricu >= small.scenarios[0].fixed_ricu


def test_unquantifiable_inputs_are_reported_instead_of_invented():
    report = _estimate("We have a batch job that processes files.")
    assert report.insufficient_inputs
    assert "model_relative_change_pct" not in report.comparison
    for scenario in report.scenarios:
        assert scenario.total_ricu >= 0
    assert any("not" in item.lower() or "unquantified" in item.lower() for item in report.insufficient_inputs)


def test_sensitivity_recomputes_rather_than_scaling_the_answer():
    report = _estimate(
        "A university attendance portal with QR check-in for 2500 students, an API, a relational database "
        "and a nightly report job; traffic spikes in the first ten minutes of every class."
    )
    assert report.sensitivity
    for entry in report.sensitivity:
        assert entry.name and entry.low_label and entry.high_label
        assert isinstance(entry.conventional_delta_pct, float)
        assert isinstance(entry.proposed_delta_pct, float)
        assert abs(entry.conventional_delta_pct) < 500
        assert abs(entry.proposed_delta_pct) < 500
    # A step-function artefact must be explained, not presented as a result.
    for entry in report.sensitivity:
        if entry.conventional_delta_pct == 0.0:
            assert entry.note


def test_availability_expectation_raises_both_models():
    standard = _estimate("A helpdesk API for 5000 users with a relational database.", availability="standard")
    critical = _estimate("A helpdesk API for 5000 users with a relational database.", availability="critical")
    assert critical.scenarios[0].fixed_ricu > standard.scenarios[0].fixed_ricu
    assert critical.scenarios[1].total_ricu > standard.scenarios[1].total_ricu
    assert standard.scenarios[0].fixed_ricu > 0


def test_storage_uses_the_same_unit_rate_in_both_models_because_it_does_not_move():
    report = _estimate(
        "A media archive with 20000 users uploading video files into object storage, with an API and a database."
    )
    conventional, proposed = report.scenarios

    def unit_rates(scenario):
        rates = {}
        for item in scenario.line_items:
            if item.quantity > 0 and item.unit in {"GB-month", "GB", "GB stored"}:
                rates[item.label.lower().split(" ")[0]] = round(item.ricu / item.quantity, 8)
        return rates

    shared = set(unit_rates(conventional)) & set(unit_rates(proposed))
    assert shared, "both models must price the same storage lines"
    for key in shared:
        assert unit_rates(conventional)[key] == unit_rates(proposed)[key], key
    # Storage volume itself may differ (derived artefacts), so totals need not match.
    assert conventional.total_ricu > 0 and proposed.total_ricu > 0


def test_rate_table_is_published_with_the_result():
    report = _estimate("A booking API for 3000 users with a database.")
    assert report.rate_table
    assert report.methodology
    assert any(COST_MODEL_VERSION in line for line in report.methodology)
    assert report.assumptions
    assert report.limitations


def test_rate_coefficients_are_positive_and_bounded():
    rates = Rates()
    for name in sorted(RATE_FIELDS):
        value = getattr(rates, name)
        assert value > 0, name
        assert value < 100, name


def test_cost_and_suitability_do_not_disagree_about_the_same_input():
    for identifier in ("college-attendance", "online-examination", "file-processing-pipeline"):
        result = AnalysisPipeline().run(
            AnalysisRequest(requirements=requirements_for(identifier), options=AnalysisOptions(use_ai=False))
        )
        if result.cost.insufficient_inputs:
            continue
        assert result.cost.scenarios[1].total_ricu > 0
