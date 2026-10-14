"""Readable report text and one export filename rule.

Enum values keep their machine form in the JSON contract; these tests pin the human-facing
text in the Markdown report and the filename shared by saved and unsaved exports.
"""

from __future__ import annotations

import re

import pytest

from app.services.labels import readable, traffic_pattern_phrase
from app.services.pipeline import run_analysis
from app.services.report_generator import export_filename, to_markdown
from app.services.templates import load_templates, requirements_for


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("object_storage", "object storage"),
        ("steady_crud", "steady CRUD"),
        ("read_heavy_crud", "read heavy CRUD"),
        ("managed_service", "managed service"),
        ("unknown", "not stated"),
        ("", "not stated"),
    ],
)
def test_enum_values_read_as_words(value, expected):
    assert readable(value) == expected


def test_unstated_traffic_pattern_is_described_without_the_word_unknown():
    assert traffic_pattern_phrase("unknown") == "an unstated traffic pattern"
    assert traffic_pattern_phrase("diurnal") == "diurnal pattern"


@pytest.mark.parametrize("template", [t.id for t in load_templates()])
def test_markdown_report_has_no_raw_enum_values_in_prose_tables(template):
    result = run_analysis(requirements_for(template), use_ai=False)
    markdown = to_markdown(result)
    # Field names and identifiers stay in code formatting. Prose and table cells that are not code
    # must not carry raw enum tokens such as "user_provided" or "object_storage".
    raw_token = re.compile(r"\b[a-z]+_[a-z_]+\b")
    for line in markdown.splitlines():
        if line.startswith(("|", "- ")):
            # Rule-trace references ("Matched lexical rule signal.x") and "field = value" evidence
            # are audit notation, not display labels, so they are not checked.
            prose = re.sub(r"Matched lexical rule \S+", "", re.sub(r"`[^`]*`", "", line))
            prose = re.sub(r"\b[a-z]+_[a-z_]+ = [^;|]+", "", prose)
            assert not raw_token.search(prose), line
    assert "unknown pattern" not in markdown


def test_export_filename_follows_the_analysis_title():
    result = run_analysis(requirements_for("online-examination"), use_ai=False)
    assert export_filename(result, "md") == "nyx-report-" + re.sub(
        r"[^A-Za-z0-9_-]", "-", result.title
    )[:48].strip("-").lower() + ".md"


def test_saved_project_exports_use_the_same_name_rule_as_unsaved_analysis(client):
    meta = client.get("/api/meta").json()
    template = next(item for item in meta["templates"] if item["id"] == "online-examination")
    created = client.post("/api/projects", json={"name": "Exams pilot", "requirements": dict(template["form"])}).json()
    result_title = created["result"]["title"]

    json_export = client.get(f"/api/projects/{created['id']}/export.json").json()
    unsaved = client.post(
        "/api/analyze/export",
        json={"requirements": dict(template["form"]), "options": {}, "format": "json"},
    ).json()

    assert json_export["filename"] == unsaved["filename"]
    assert created["id"] not in json_export["filename"]
    assert json_export["filename"].startswith("nyx-report-")
    assert result_title  # the name is derived from the analysis title, not the project id
    markdown = client.get(f"/api/projects/{created['id']}/report.md")
    assert markdown.headers["content-disposition"].endswith(
        export_filename(run_analysis(requirements_for("online-examination"), use_ai=False), "md") + '"'
    )
