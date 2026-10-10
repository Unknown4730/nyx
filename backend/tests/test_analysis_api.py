"""`POST /api/analyze` contract: full result, validation errors, determinism."""

from __future__ import annotations

import pytest

from app.schemas.analysis import AnalysisResult
from app.schemas.common import CloudProvider


def _post_analysis(client, payload):
    response = client.post("/api/analyze", json=payload)
    return response


def test_valid_request_returns_every_analysis_section(client, analysis_payload):
    response = _post_analysis(client, analysis_payload())
    assert response.status_code == 200
    body = response.json()
    for key in (
        "schema_version",
        "analysis_id",
        "created_at",
        "title",
        "application",
        "signals",
        "assumptions",
        "open_questions",
        "workload",
        "component_inventory",
        "architectures",
        "primary_view",
        "mapping_table",
        "suitability",
        "security",
        "cost",
        "migration",
        "ai",
        "providers",
        "default_provider",
        "limitations",
    ):
        assert key in body, f"missing top-level section {key}"
    assert body["schema_version"] == "nyx.analysis/1"
    assert {graph["id"] for graph in body["architectures"]} == {"conventional", "proposed"}
    assert body["primary_view"] == "proposed"
    assert body["providers"] == ["aws", "gcp", "azure"]
    assert len(body["component_inventory"]) >= 5
    assert body["suitability"]["factors"]
    assert body["cost"]["scenarios"]


def test_result_validates_against_the_strict_schema(client, analysis_payload):
    body = _post_analysis(client, analysis_payload(name="Strict Schema Check")).json()
    result = AnalysisResult.model_validate(body)
    assert result.title == "Strict Schema Check"
    # Aliases are used for transport, so re-serialisation must be lossless.
    assert result.to_json_dict()["analysis_id"] == body["analysis_id"]


def test_missing_description_is_a_structured_validation_error(client, requirements_factory):
    requirements = requirements_factory().model_dump(mode="json")
    requirements.pop("description")
    response = _post_analysis(client, {"requirements": requirements})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert any("description" in detail for detail in error["details"])
    assert "traceback" not in response.text.lower()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"requirements": {}},
        {"requirements": {"name": "ok", "description": "x" * 5000}},
        {"requirements": {"name": "", "description": "anything at all here"}},
        {"requirements": {"name": "x" * 500, "description": "short"}},
        {"requirements": {"name": "ok", "description": "text", "expected_users": -5}},
        {"requirements": {"name": "ok", "description": "text", "traffic_pattern": "telepathic"}},
        {"requirements": {"name": "ok", "description": "text"}, "options": {"max_operations_per_view": 400}},
        {"unknown_top_level": True},
    ],
)
def test_invalid_input_is_rejected_not_guessed(client, payload):
    response = _post_analysis(client, payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_analysis_is_reproducible(client, analysis_payload):
    first = _post_analysis(client, analysis_payload()).json()
    second = _post_analysis(client, analysis_payload()).json()
    assert first["suitability"] == second["suitability"]
    assert first["architectures"] == second["architectures"]
    assert first["cost"] == second["cost"]
    assert first["migration"] == second["migration"]
    assert first["analysis_id"] != second["analysis_id"]


def test_unknown_description_still_produces_an_honest_result(client):
    response = _post_analysis(
        client, {"requirements": {"name": "Mystery app", "description": "It is an app. We use some software."}}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["suitability"]["outcome"] == "further_assessment_required"
    assert body["open_questions"]
    assert body["suitability"]["missing_inputs"]


def test_provider_selection_changes_labels_only(client, analysis_payload):
    aws = _post_analysis(client, {**analysis_payload(), "options": {"default_provider": "aws"}}).json()
    gcp = _post_analysis(client, {**analysis_payload(), "options": {"default_provider": "gcp"}}).json()
    assert aws["default_provider"] == "aws"
    assert gcp["default_provider"] == "gcp"
    # Same topology, different labels.
    assert {c["id"] for c in aws["architectures"][1]["components"]} == {c["id"] for c in gcp["architectures"][1]["components"]}
    aws_by_id = {c["id"]: c for c in aws["architectures"][1]["components"]}
    gcp_by_id = {c["id"]: c for c in gcp["architectures"][1]["components"]}
    differing = [
        component_id
        for component_id, component in aws_by_id.items()
        if component["mappings"]["aws"]["service_name"] != gcp_by_id[component_id]["mappings"]["gcp"]["service_name"]
    ]
    assert differing, "provider selection had no effect on labels"
    assert aws["suitability"]["score"] == gcp["suitability"]["score"]


def test_max_operations_is_applied_with_a_caveat(client, analysis_payload, requirements_factory):
    rich = requirements_factory(
        description=(
            "A multi-tenant online examination platform for 100000 students: authenticated API, transactional "
            "database, Redis sessions, file storage for PDF answer scripts, transcoding workers on a queue, "
            "email and SMS notifications, search indexing, an admin analytics dashboard, object detection for "
            "proctoring, websocket realtime proctoring, and a nightly report generator."
        )
    )
    full = _post_analysis(client, {"requirements": rich.model_dump(mode="json")}).json()
    limited = _post_analysis(
        client,
        {"requirements": rich.model_dump(mode="json"), "options": {"max_operations_per_view": 6}},
    ).json()
    assert len(full["architectures"][1]["components"]) > len(limited["architectures"][1]["components"])
    assert limited["architectures"][1]["components"]
    assert limited["architectures"][1]["caveats"], "truncation must be disclosed in the view"
    assert len(limited["architectures"][1]["components"]) <= 6


def test_unicode_and_quoted_input_are_handled(client):
    response = _post_analysis(
        client,
        {
            "requirements": {
                "name": 'Attendance "portal" —semester 2026',
                "description": (
                    "A student attendance portal with \"QR scan\" login for 2,500 students across 60 rooms; "
                    "peak is 80 requests/minute; data retention is 4 years. 费用: 低预算。"
                ),
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "Attendance" in body["title"]
    assert body["application"]["name"] == 'Attendance "portal" \u2014semester 2026'
    assert body["signals"]["expected_users"] == 2500


def test_export_endpoint_returns_the_report(client, analysis_payload):
    response = client.post("/api/analyze/export", json={**analysis_payload(), "format": "markdown"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "markdown"
    assert payload["content"].startswith("# NYX — Cloud Architecture Analysis Report")

    json_response = client.post("/api/analyze/export", json={**analysis_payload(), "format": "json"})
    assert json_response.status_code == 200
    assert '"schema_version": "nyx.analysis/1"' in json_response.json()["content"]


def test_export_endpoint_validates_input(client):
    response = client.post("/api/analyze/export", json={"requirements": {"name": "x"}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_options_enum_coercion_from_api_strings(client, analysis_payload):
    body = _post_analysis(
        client,
        {
            **analysis_payload(),
            "options": {"providers": ["azure", "aws", "azure"], "default_provider": "azure"},
        },
    ).json()
    assert body["default_provider"] == "azure"
    assert CloudProvider("aws") in AnalysisResult.model_validate(body).providers
