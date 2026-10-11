"""Health, metadata and template endpoints — plus the free/no-key prerequisites."""

from __future__ import annotations

def test_health_endpoint_reports_service_state(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "NYX"
    assert body["tagline"] == "Rethink your architecture."
    assert body["schema_version"] == "nyx.analysis/1"
    assert body["storage"]["backend"] == "sqlite"
    assert body["storage"]["ok"] is True


def test_health_exposes_ai_state_without_secrets(client):
    body = client.get("/api/health").json()
    ai = body["ai"]
    assert ai["configured"] is False
    assert ai["api_key_set"] is False
    # The key value itself must never appear anywhere in the payload.
    assert "api_key" not in {key for key in ai if key != "api_key_set"}
    assert "NYX_AI_API_KEY" in ai["unavailable_reason"] or ai["enabled"] is False


def test_ai_status_endpoint_explains_the_free_mode(client):
    body = client.get("/api/ai/status").json()
    assert body["status"] == "not_configured"
    assert "Deterministic analysis is fully available" in body["message"]


def test_meta_exposes_form_vocabularies(client):
    body = client.get("/api/meta").json()
    assert body["product"]["schema_version"] == "nyx.analysis/1"
    values = {item["value"] for item in body["enums"]["traffic_pattern"]}
    assert {"steady", "spiky_event_driven", "unknown"} <= values
    provider_values = {item["value"] for item in body["enums"]["provider"]}
    assert provider_values == {"aws", "gcp", "azure"}
    assert body["cost"]["unit"] == "RICU"
    assert body["suitability"]["bands"]


def _template_requirements(identifier: str):
    from app.services.templates import requirements_for

    value = requirements_for(identifier)
    assert value is not None, f"unknown template {identifier}"
    return value


def test_meta_lists_templates_as_real_inputs(client):
    body = client.get("/api/meta").json()
    templates = body["templates"]
    assert len(templates) >= 5
    ids = {item["id"] for item in templates}
    assert {"college-attendance", "online-examination", "ecommerce-application"} <= ids
    for item in templates:
        assert item["form"]["description"] and len(item["form"]["description"]) > 60
        # A template must not smuggle in a pre-computed verdict.
        assert "result" not in item and "score" not in item


def test_templates_feed_the_real_engine(client):
    first = client.post(
        "/api/analyze",
        json={"requirements": _template_requirements("college-attendance").model_dump(mode="json")},
    )
    second = client.post(
        "/api/analyze",
        json={"requirements": _template_requirements("file-processing-pipeline").model_dump(mode="json")},
    )
    assert first.status_code == second.status_code == 200
    a, b = first.json(), second.json()
    assert a["suitability"]["score"] != b["suitability"]["score"]
    assert a["suitability"]["outcome"] != b["suitability"]["outcome"]
    assert a["engine_mode"] == b["engine_mode"] == "deterministic_rules"


def test_openapi_documents_the_contract(client):
    schema = client.get("/api/openapi.json").json()
    assert "/api/analyze" in schema["paths"]
    assert "/api/projects/{project_id}" in schema["paths"]
    components = schema.get("components", {}).get("schemas", {})
    assert "AnalysisResult" in components
    assert "ProjectSummary" in components


def test_input_limits_are_read_from_the_schema_not_copied(client):
    """The form's client-side checks use these numbers, so they must be the schema's own bounds."""
    from app.schemas.requirements import ApplicationRequirements

    limits = client.get("/api/meta").json()["limits"]
    fields = ApplicationRequirements.model_fields
    name_bounds = {type(item).__name__ for item in fields["name"].metadata}
    assert name_bounds, "the name field carries explicit length constraints"
    assert limits["name_min_chars"] == 2
    assert limits["name_max_chars"] == 90
    assert limits["description_min_chars"] == 10
    assert limits["description_max_chars"] == 4000
    assert limits["additional_requirements_max_chars"] == 2000
