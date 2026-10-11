"""Report rendering: Markdown and JSON exports must agree with the analysis object."""

from __future__ import annotations

import json
import re

import pytest

from app.schemas.analysis import AnalysisOptions, AnalysisRequest, AnalysisResult
from app.schemas.requirements import ApplicationRequirements
from app.services.pipeline import AnalysisPipeline
from app.services.report_generator import to_json, to_markdown
from app.services.templates import requirements_for

PIPELINE = AnalysisPipeline()


@pytest.fixture(scope="module")
def exam_result():
    return PIPELINE.run(
        AnalysisRequest(requirements=requirements_for("online-examination"), options=AnalysisOptions(use_ai=False))
    )


@pytest.mark.parametrize(
    "identifier",
    ["college-attendance", "online-examination", "ecommerce-application", "food-delivery-platform",
     "file-processing-pipeline"],
)
def test_markdown_covers_every_analysis_area(identifier):
    result = PIPELINE.run(
        AnalysisRequest(requirements=requirements_for(identifier), options=AnalysisOptions(use_ai=False))
    )
    text = to_markdown(result)
    for heading in (
        "## 1. Application overview",
        "## 2. Extracted workload characteristics",
        "## 3. Assumptions and open questions",
        "## 4. Serverless suitability",
        "## 5. Architecture blueprints",
        "## 6. Multi-cloud service mapping",
        "## 7. Security findings",
        "## 8. Relative cost comparison",
        "## 9. Migration assessment",
        "## 10. Limitations and disclosures",
    ):
        assert heading in text, heading
    assert len(text) > 4000
    assert result.title.split()[0] in text or result.application.name in text


def test_markdown_quotes_the_numbers_and_labels_from_the_result(exam_result):
    text = to_markdown(exam_result)
    assert f"{exam_result.suitability.score:.0f}/100" in text
    assert exam_result.suitability.outcome.value.replace("_", " ") in text
    for scenario in exam_result.cost.scenarios:
        assert f"{scenario.total_ricu:.2f}" in text
    for factor in exam_result.suitability.factors[:4]:
        assert factor.name in text
        assert f"{factor.weight:.2f}" in text
        assert f"{factor.impact:+.2f}" in text
    for phase in exam_result.migration.phases:
        assert phase.title in text
    for row in exam_result.mapping_table[:3]:
        assert row.component_label in text
    # Provider names must appear for all three clouds.
    for service in ("AWS", "Google Cloud", "Azure"):
        assert service in text


def test_markdown_carries_the_honesty_statements(exam_result):
    text = to_markdown(exam_result)
    assert "Relative Infrastructure Cost Unit" in text
    assert "conceptual blueprints" in text
    assert "does not publish durations" in text
    assert "not an industry benchmark" in text or "heuristic" in text
    assert "deterministic local rules engine" in text
    assert not re.search(r"(₹|\bUSD\b|\bINR\b)", text)


def test_provisional_results_say_so_in_the_report():
    result = PIPELINE.run(
        AnalysisRequest(
            requirements=requirements_for("file-processing-pipeline"), options=AnalysisOptions(use_ai=False)
        )
    )
    text = to_markdown(result)
    assert "further assessment" in text.lower()
    if result.cost.insufficient_inputs:
        assert "Inputs that were not sufficient" in text
    assert "provisional" in text.lower()


def test_json_export_round_trips_into_the_same_analysis():
    result = PIPELINE.run(
        AnalysisRequest(requirements=requirements_for("ecommerce-application"), options=AnalysisOptions(use_ai=False))
    )
    payload = json.loads(to_json(result))
    assert payload["export"]["generator"] == "NYX"
    body = {key: value for key, value in payload.items() if key != "export"}
    rebuilt = AnalysisResult.model_validate(body)
    assert rebuilt.analysis_id == result.analysis_id
    assert rebuilt.suitability.model_dump() == result.suitability.model_dump()
    assert rebuilt.architectures[1].model_dump() == result.architectures[1].model_dump()
    assert rebuilt.cost.model_dump() == result.cost.model_dump()


def test_json_export_is_valid_json_for_every_template():
    for identifier in ("college-attendance", "online-examination", "ecommerce-application",
                       "food-delivery-platform", "file-processing-pipeline"):
        result = PIPELINE.run(
            AnalysisRequest(requirements=requirements_for(identifier), options=AnalysisOptions(use_ai=False))
        )
        text = to_json(result)
        parsed = json.loads(text)
        assert parsed["schema_version"] == "nyx.analysis/1"
        assert "architectures" in parsed and len(parsed["architectures"]) == 2


def test_report_uses_the_ai_note_only_when_the_ai_layer_actually_ran():
    deterministic = PIPELINE.run(
        AnalysisRequest(requirements=requirements_for("college-attendance"), options=AnalysisOptions(use_ai=False))
    )
    assert "Appendix — AI layer" not in to_markdown(deterministic)

    class Stub:
        name = "stub"

        def available(self) -> bool:
            return False

        def complete_json(self, *, system: str, user: str):  # type: ignore[no-untyped-def]
            raise AssertionError("must not be called")

    assisted = AnalysisPipeline(ai_provider=Stub()).run(
        AnalysisRequest(requirements=requirements_for("college-attendance"), options=AnalysisOptions(use_ai=False))
    )
    assert assisted.engine_mode == deterministic.engine_mode
    assert to_markdown(assisted).count("## 1. Application overview") == 1


def test_report_survives_a_minimal_input():
    result = PIPELINE.run(
        AnalysisRequest(
            requirements=ApplicationRequirements(name="Tiny", description="A small internal notes tool."),
            options=AnalysisOptions(use_ai=False),
        )
    )
    text = to_markdown(result)
    assert "No assumptions were needed" in text or "Assumptions" in text
    assert "## 9. Migration assessment" in text
    assert "unspecified" not in text.lower()[:200]


def test_user_text_cannot_break_markdown_table_rows():
    """Pipes and line breaks typed by a user must not add or break table columns."""
    from app.services.report_generator import _c

    assert _c("A | B\nC") == "A \\| B C"
    assert _c("back\\slash") == "back\\\\slash"
    # Built through the validated constructor, as the API does (validators collapse whitespace).
    requirements = ApplicationRequirements(
        name="Ops | Team\nLine two",
        description="A college attendance portal with pipes | in notes and relational data for 300 staff.",
        additional_requirements="Use | pipes and\nnewlines",
    )
    result = AnalysisPipeline().run(AnalysisRequest(requirements=requirements, options=AnalysisOptions(use_ai=False)))
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in to_markdown(result).splitlines():
        if line.startswith("|") and line.endswith("|"):
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    assert len(blocks) >= 3, "the report should contain several tables"
    for block in blocks:
        column_counts = {line.replace("\\|", "").count("|") for line in block}
        assert len(column_counts) == 1, block
