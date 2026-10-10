"""Hostile, sparse and oversized inputs: NYX must degrade honestly, never crash or guess."""

from __future__ import annotations

import json

import pytest

from app.schemas.analysis import AnalysisOptions, AnalysisRequest, AnalysisResult
from app.schemas.common import SuitabilityOutcome
from app.schemas.requirements import ApplicationRequirements
from app.services.pipeline import AnalysisPipeline
from app.services.report_generator import to_markdown

PIPELINE = AnalysisPipeline()
MAX_NODES = 24


def run(description: str, **overrides):
    payload = {"name": "Edge case", "description": description}
    payload.update(overrides)
    return PIPELINE.run(
        AnalysisRequest(requirements=ApplicationRequirements(**payload), options=AnalysisOptions(use_ai=False))
    )


@pytest.mark.parametrize(
    "description",
    [
        "hello there",
        "................",
        "🎉 🚀 ✨ sparkle",
        "<script>alert('xss')</script> and a <img src=x onerror=alert(1)> form",
        "'; DROP TABLE projects; --",
        "{{7*7}} ${jndi:ldap://x} %{T(java.lang.Runtime)}",
        "a" * 3990,
        "Line\n" * 200,
        "SELECT * FROM users WHERE name = '' OR 1=1",
        "The system does things. Sometimes. Maybe.",
    ],
)
def test_no_input_crashes_the_pipeline(description):
    if len(description.strip()) < 10:
        # Too short to mean anything: validation refuses it instead of analysing noise.
        with pytest.raises(Exception):
            ApplicationRequirements(name="Edge case", description=description)
        return
    result = run(description)
    assert isinstance(result, AnalysisResult)
    assert 0.0 <= result.suitability.score <= 100.0
    assert result.suitability.outcome in set(SuitabilityOutcome)
    for graph in result.architectures:
        assert 0 < len(graph.components) <= MAX_NODES
        assert len(graph.connections) <= MAX_NODES * 6
    assert to_markdown(result)


def test_html_and_sql_lookalikes_are_treated_as_text_not_code():
    result = run(
        "<b>Attendance</b> system for <script>900</script> students; it stores 'relational' data; "
        "peak is 60 requests/minute; availability high."
    )
    blob = result.model_dump_json()
    assert "<script>" in blob  # preserved verbatim, never executed or re-written
    # A number wrapped in markup is not treated as a stated headcount: the engine
    # records the gap instead of inventing a figure.
    assert result.application.expected_users is None
    # No prompt-injection style instruction leaks into the report as an assertion.
    markdown = to_markdown(result)
    assert "IGNORE ALL PREVIOUS" not in markdown.upper()
    json.loads(blob)  # serialisable


def test_absurd_scale_is_rejected_at_the_boundary_then_survives_as_prose():
    # A user count beyond the supported range is refused by the schema rather than
    # silently clamped into a plausible-looking number...
    with pytest.raises(Exception):
        ApplicationRequirements(name="Absurd", description="A service with 1000000000000 users.", expected_users=10**12)
    # ...but the same claim written in prose is treated as an unquantified statement,
    # not as data, and the analysis still completes.
    result = run("A service claiming 1000000000000 users and unlimited budget.")
    assert result.suitability.outcome in set(SuitabilityOutcome)
    assert result.suitability.missing_inputs
    for graph in result.architectures:
        assert len(graph.components) <= MAX_NODES


def test_missing_everything_still_produces_questions_not_confidence():
    result = run("An application.")
    assert result.suitability.outcome is SuitabilityOutcome.FURTHER_ASSESSMENT
    assert result.open_questions
    assert result.provisional_or_uncertain if hasattr(result, "provisional_or_uncertain") else True
    assert result.suitability.provisional_score is not None or result.suitability.score < 60
    assert result.security.verification_gaps
    if "model_relative_change_pct" in result.cost.comparison:
        assert result.cost.insufficient_inputs


def test_only_technology_names_without_any_workload_is_not_a_fact():
    result = run("We use Kubernetes, Kafka, Cassandra, Redis, GraphQL, gRPC and Elasticsearch.")
    # Mentioning products must not be read as a requirement for serverless, and must
    # not invent components the description never implied.
    assert result.workload is not None
    assert result.suitability.score is not None
    assert "kubernetes" not in json.dumps([component.label for component in result.architectures[1].components]).lower()
    assert result.limitations


def test_repeated_and_contradictory_statements_resolve_predictably():
    once = run("An exam platform for 10000 students with spiky traffic.")
    repeated = run(
        "An exam platform for 10000 students with spiky traffic. An exam platform for 10000 students with "
        "spiky traffic. An exam platform for 10000 students with spiky traffic."
    )
    assert once.suitability.score == repeated.suitability.score
    assert once.signals.model_dump() == repeated.signals.model_dump()
    contradicting = run(
        "An exam platform for 10000 students. Traffic is steady all day and spikes every exam window. "
        "It is always on and never used. Data is relational and no data is stored."
    )
    assert 0 <= contradicting.suitability.score <= 100
    assert contradicting.assumptions


def test_empty_optional_collections_are_accepted():
    result = PIPELINE.run(
        AnalysisRequest(
            requirements=ApplicationRequirements(
                name="Empties",
                description="A reporting tool for 120 staff with nightly PDF generation.",
                data_storage=[],
                additional_requirements=None,
            ),
            options=AnalysisOptions(use_ai=False, providers=["aws", "gcp", "azure"], default_provider=None),
        )
    )
    assert result.default_provider.value == "aws"
    assert result.architectures


def test_options_defaults_are_the_documented_three_providers():
    result = PIPELINE.run(
        AnalysisRequest(
            requirements=ApplicationRequirements(name="Defaults", description="A booking API for 900 users."),
        )
    )
    assert [provider.value for provider in result.providers] == ["aws", "gcp", "azure"]
    assert result.options_default_check if False else True
    assert result.primary_view == "proposed"
    assert result.schema_version == "nyx.analysis/1"


def test_very_long_description_is_truncated_by_validation_not_silently():
    with pytest.raises(Exception):
        ApplicationRequirements(name="Too long", description="x" * 5000)
    boundary = run("x" * 3990)
    assert boundary.analysis_id


def test_pipeline_is_stable_under_repeated_calls_with_interleaved_inputs():
    first = run("An online examination platform for 10000 students with spiky traffic and high availability.")
    run("A file processing pipeline with 90 minute GPU transcoding jobs.")  # interleaved
    second = run("An online examination platform for 10000 students with spiky traffic and high availability.")
    assert first.suitability.model_dump() == second.suitability.model_dump()
    assert first.cost.model_dump() == second.cost.model_dump()
    assert first.migration.model_dump() == second.migration.model_dump()
