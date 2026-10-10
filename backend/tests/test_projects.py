"""Saved projects: create, list, update, delete, JSON export, and survival across a restart."""

from __future__ import annotations

import json

import pytest

from app.database.project_store import ProjectNotFound, ProjectStore
from app.schemas.analysis import AnalysisResult, ProjectDetail, ProjectSummary
from app.schemas.common import ProjectKind


@pytest.fixture()
def payload(client):
    meta = client.get("/api/meta").json()
    template = next(item for item in meta["templates"] if item["id"] == "online-examination")
    # The project label is separate from the requirement's application name:
    # one is how the user files it, the other is what NYX analyses.
    return {"name": "Exams pilot", "requirements": dict(template["form"])}


def test_creating_a_project_runs_the_analysis_and_returns_the_full_result(client, payload):
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 201
    detail = response.json()
    assert detail["name"] == "Exams pilot"
    assert detail["result"]["application"]["name"]
    assert detail["requirements"]["description"] == payload["requirements"]["description"]
    assert detail["kind"] == "user_project"
    assert detail["result"]["schema_version"] == "nyx.analysis/1"
    assert detail["result"]["suitability"]["score"] > 0
    assert len(detail["result"]["architectures"]) == 2
    ProjectDetail.model_validate(detail)


def test_project_appears_in_the_list_with_summary_fields(client, payload):
    created = client.post("/api/projects", json=payload).json()
    listed = client.get("/api/projects").json()
    assert any(item["id"] == created["id"] for item in listed)
    summary = next(item for item in listed if item["id"] == created["id"])
    ProjectSummary.model_validate(summary)
    assert summary["suitability_score"] == pytest.approx(created["result"]["suitability"]["score"], abs=0.05)
    assert summary["suitability_outcome"] == created["result"]["suitability"]["outcome"]
    assert summary["component_count"] == len(created["result"]["architectures"][1]["components"])
    assert summary["finding_count"] == len(created["result"]["security"]["findings"])
    assert summary["engine_mode"] == "deterministic_rules"
    assert summary["excerpt"] and len(summary["excerpt"]) <= 240


def test_project_survives_a_restart(client, payload, store, tmp_path):
    created = client.post("/api/projects", json=payload).json()
    # Simulate a restart by opening the same file with a fresh store instance.
    reopened = ProjectStore(str(tmp_path / "projects.sqlite3"))
    detail = reopened.get(created["id"])
    assert detail.id == created["id"]
    assert detail.result.model_dump() == AnalysisResult.model_validate(created["result"]).model_dump()
    assert reopened.stats()["total"] == 1
    reopened.close()


def test_rename_and_notes_update_without_losing_the_result(client, payload):
    created = client.post("/api/projects", json=payload).json()
    response = client.put(f"/api/projects/{created['id']}", json={"name": "Renamed", "notes": "for the viva"})
    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "Renamed"
    assert updated["id"] == created["id"]
    assert updated["result"]["analysis_id"] == created["result"]["analysis_id"]
    assert updated["updated_at"] >= updated["created_at"]


def test_reanalyse_replaces_the_result_and_keeps_the_identity(client, payload):
    created = client.post("/api/projects", json=payload).json()
    requirements = dict(created["result"]["application"])
    requirements.pop("provenance", None)
    requirements["description"] = (
        "An online examination platform for 250000 students with 90-minute timed sessions, GPU proctoring "
        "inference that always runs, and websocket-based invigilation that keeps connections open for hours."
    )
    response = client.put(f"/api/projects/{created['id']}", json={"reanalyze": True, "requirements": requirements})
    assert response.status_code == 200
    refreshed = response.json()
    assert refreshed["result"]["suitability"]["score"] != created["result"]["suitability"]["score"]
    assert refreshed["id"] == created["id"]


def test_deleting_removes_the_row(client, payload):
    created = client.post("/api/projects", json=payload).json()
    assert client.delete(f"/api/projects/{created['id']}").json() == {"deleted": True, "id": created["id"]}
    assert client.get(f"/api/projects/{created['id']}").status_code == 404
    assert all(item["id"] != created["id"] for item in client.get("/api/projects").json())


def test_unknown_project_id_returns_a_structured_404(client):
    for path in (
        "/api/projects/does-not-exist",
        "/api/projects/does-not-exist/export.json",
        "/api/projects/does-not-exist/report.md",
        "/api/projects/does-not-exist/graph",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND", path
    assert client.put("/api/projects/does-not-exist", json={"name": "Renamed"}).status_code == 404
    assert client.delete("/api/projects/does-not-exist").status_code == 404


def test_invalid_project_payload_is_rejected(client):
    assert client.post("/api/projects", json={}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "requirements": {}}).status_code == 422
    assert client.put("/api/projects/whatever", json={"name": ""}).status_code == 422


def test_json_export_endpoint_returns_the_full_result(client, payload):
    created = client.post("/api/projects", json=payload).json()
    response = client.get(f"/api/projects/{created['id']}/export.json")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    export = response.json()
    assert export["format"] == "json"
    assert export["filename"].endswith(".json")
    parsed = json.loads(export["content"])
    assert parsed["export"]["generator"] == "NYX"
    assert AnalysisResult.model_validate({key: value for key, value in parsed.items() if key != "export"})
    assert parsed["suitability"]["score"] == created["result"]["suitability"]["score"]


def test_markdown_report_endpoint(client, payload):
    created = client.post("/api/projects", json=payload).json()
    response = client.get(f"/api/projects/{created['id']}/report.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("# NYX — Cloud Architecture Analysis Report")
    assert "## 4. Serverless suitability" in response.text


def test_graph_projection_for_each_view_and_provider(client, payload):
    created = client.post("/api/projects", json=payload).json()
    for view in ("conventional", "proposed"):
        for provider_name in ("aws", "gcp", "azure"):
            response = client.get(
                f"/api/projects/{created['id']}/graph", params={"view": view, "provider": provider_name}
            )
            assert response.status_code == 200
            graph = response.json()
            assert graph["view"] == view
            assert graph["provider"] == provider_name
            assert graph["nodes"] and graph["edges"]
            for node in graph["nodes"]:
                assert {"id", "label", "type", "position", "service"} <= set(node)
                assert node["position"]["x"] is not None
            assert all(node["service"] for node in graph["nodes"])
    bad = client.get(f"/api/projects/{created['id']}/graph", params={"view": "nonsense"})
    assert bad.status_code == 422


def test_provider_labels_in_the_projection_match_the_stored_result(client, payload):
    created = client.post("/api/projects", json=payload).json()
    aws = client.get(f"/api/projects/{created['id']}/graph", params={"view": "proposed", "provider": "aws"}).json()
    gcp = client.get(f"/api/projects/{created['id']}/graph", params={"view": "proposed", "provider": "gcp"}).json()
    assert [node["id"] for node in aws["nodes"]] == [node["id"] for node in gcp["nodes"]]
    assert {node["service"] for node in aws["nodes"]} != {node["service"] for node in gcp["nodes"]}


def test_listing_supports_paging_and_kind_filters(client, payload):
    ids = [client.post("/api/projects", json=payload).json()["id"] for _ in range(3)]
    page = client.get("/api/projects", params={"limit": 2, "offset": 0}).json()
    assert len(page) == 2
    second_page = client.get("/api/projects", params={"limit": 2, "offset": 2}).json()
    assert {item["id"] for item in page} | {item["id"] for item in second_page} == set(ids)
    assert client.get("/api/projects", params={"kind": "example_project"}).json() == []
    assert all(item["kind"] == "user_project" for item in client.get("/api/projects").json())
    assert client.get("/api/projects", params={"limit": 0}).status_code == 422
    assert client.get("/api/projects", params={"limit": 5000}).status_code == 422


def test_store_roundtrip_and_deleting_a_missing_row_raises(store, client, payload):
    created = client.post("/api/projects", json=payload).json()
    with pytest.raises(ProjectNotFound):
        store.get("prj-missing")
    detail = store.get(created["id"])
    assert isinstance(detail, ProjectDetail)
    assert detail.kind is ProjectKind.USER
    assert store.delete("prj-missing") is False


def test_seeded_examples_are_labelled_as_examples(tmp_path):
    from app.seed import seed_example_projects

    seeded_store = ProjectStore(str(tmp_path / "seed.sqlite3"))
    created = seed_example_projects(seeded_store)
    assert created >= 3
    summaries = seeded_store.list(limit=50)
    assert all(item.kind is ProjectKind.EXAMPLE for item in summaries)
    for item in summaries:
        assert "example" in item.name.lower()
    # Seeding is idempotent.
    assert seed_example_projects(seeded_store) == 0
    assert seeded_store.stats()["total"] == created
    # Examples carry the same schema as user analyses, including the honest labels.
    detail = seeded_store.get(summaries[0].id)
    assert detail.result.engine_mode.value == "deterministic_rules"
    assert any(limitation.code == "LIM-SCOPE" for limitation in detail.result.limitations)
    seeded_store.close()
