#!/usr/bin/env python3
"""Live API smoke test for a running NYX backend.

Run it against a backend that is already started (see docs/DEMO_RUNBOOK.md):

    python scripts/api_smoke.py                       # http://127.0.0.1:8000
    python scripts/api_smoke.py --base http://127.0.0.1:8000

It uses only the Python standard library and exercises real HTTP requests: health,
metadata, every sample template, validation failure, both export paths, the full
project lifecycle and the error envelope for an unknown project. It exits with status 0
only when every check passes, so it can be used as a readiness gate before a demo.

The expected sample results (EXPECTED_SAMPLE_OUTCOMES) are the documented values of
rule pack 2026.10, copied from docs/DEMO_RUNBOOK.md. If a rule change is deliberate,
update both places together. Nothing is written except one temporary project, which the
script deletes at the end.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

# Documented results of the deterministic rules engine for the five samples (rule pack 2026.10).
EXPECTED_SAMPLE_OUTCOMES: dict[str, tuple[float, str]] = {
    "college-attendance": (69.0, "suitable_with_modifications"),
    "online-examination": (78.1, "strong_candidate"),
    "ecommerce-application": (77.1, "suitable_with_modifications"),
    "food-delivery-platform": (75.3, "suitable_with_modifications"),
    "file-processing-pipeline": (53.9, "further_assessment_required"),  # provisional score 67.0
}


@dataclass
class Report:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        line = f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else "")
        print(line)
        (self.passed if ok else self.failed).append(name)


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body: object | None = None) -> tuple[int, str, str]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json, text/markdown, */*"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, response.headers.get("Content-Type", ""), response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get("Content-Type", ""), error.read().decode("utf-8", "replace")

    def json(self, method: str, path: str, body: object | None = None) -> tuple[int, object]:
        status, _content_type, text = self.call(method, path, body)
        try:
            return status, json.loads(text)
        except json.JSONDecodeError:
            return status, {"_raw": text[:200]}


def run(base: str) -> int:
    api = Api(base)
    report = Report()

    status, health = api.json("GET", "/api/health")
    report.check("health reports ok", status == 200 and isinstance(health, dict) and health.get("status") == "ok")

    status, meta = api.json("GET", "/api/meta")
    limits = meta.get("limits", {}) if isinstance(meta, dict) else {}
    report.check(
        "metadata exposes schema-derived input limits",
        status == 200 and limits.get("name_min_chars") == 2 and limits.get("description_min_chars") == 10,
        f"name_min={limits.get('name_min_chars')} description_min={limits.get('description_min_chars')}",
    )
    templates = {item["id"]: item for item in meta.get("templates", [])} if isinstance(meta, dict) else {}
    report.check("metadata lists the five samples", set(templates) == set(EXPECTED_SAMPLE_OUTCOMES), ", ".join(sorted(templates)))

    for template_id, (expected_score, expected_outcome) in EXPECTED_SAMPLE_OUTCOMES.items():
        template = templates.get(template_id)
        if template is None:
            report.check(f"sample {template_id} analyses", False, "missing from metadata")
            continue
        status, result = api.json("POST", "/api/analyze", {"requirements": template["form"], "options": {"use_ai": False}})
        if status != 200 or not isinstance(result, dict):
            report.check(f"sample {template_id} analyses", False, f"HTTP {status}")
            continue
        suitability = result["suitability"]
        # A provisional verdict publishes the blended number as `provisional_score` and the
        # workload score as `score`; the documented value is the one a user sees.
        shown = suitability["score"]
        provisional = suitability.get("provisional_score")
        ok = abs(float(shown) - expected_score) < 0.05 and suitability["outcome"] == expected_outcome
        if expected_outcome == "further_assessment_required":
            ok = ok and provisional is not None and abs(float(provisional) - 67.0) < 0.05
        report.check(
            f"sample {template_id} matches documented result",
            ok,
            f"score {shown}, provisional {provisional}, outcome {suitability['outcome']}",
        )
        report.check(
            f"sample {template_id} returns both architecture views",
            sorted(graph["id"] for graph in result["architectures"]) == ["conventional", "proposed"],
        )

    sample = templates.get("online-examination", {}).get("form")
    if sample:
        status, error = api.json("POST", "/api/analyze", {"requirements": {"name": "A", "description": "short"}})
        details = error.get("error", {}).get("details", []) if isinstance(error, dict) else []
        report.check(
            "invalid input returns 422 with field-scoped details",
            status == 422 and any(item.startswith("requirements.name") for item in details),
            f"{len(details)} detail(s)",
        )

        status, envelope = api.json(
            "POST", "/api/analyze/export", {"requirements": sample, "options": {"use_ai": False}, "format": "markdown"}
        )
        content = envelope.get("content", "") if isinstance(envelope, dict) else ""
        report.check(
            "unsaved markdown export returns an envelope with a report",
            status == 200 and envelope.get("format") == "markdown" and content.startswith("# NYX"),
        )

        status, envelope = api.json(
            "POST", "/api/analyze/export", {"requirements": sample, "options": {"use_ai": False}, "format": "json"}
        )
        try:
            exported = json.loads(envelope.get("content", "")) if isinstance(envelope, dict) else {}
        except json.JSONDecodeError:
            exported = {}
        report.check("unsaved JSON export envelope contains a parseable analysis", status == 200 and "suitability" in exported)

        status, created = api.json(
            "POST",
            "/api/projects",
            {"name": "Smoke test project", "requirements": sample, "options": {"use_ai": False}},
        )
        project_id = created.get("id") if isinstance(created, dict) else None
        report.check("project is saved (201)", status == 201 and bool(project_id), str(project_id))

        if project_id:
            try:
                status, reopened = api.json("GET", f"/api/projects/{project_id}")
                report.check(
                    "saved project reopens with the same verdict",
                    status == 200 and reopened["result"]["suitability"]["score"] == created["result"]["suitability"]["score"],
                )
                status, renamed = api.json("PUT", f"/api/projects/{project_id}", {"name": "Smoke test renamed"})
                report.check("project can be renamed", status == 200 and renamed.get("name") == "Smoke test renamed")
                status, _ctype, markdown_text = api.call("GET", f"/api/projects/{project_id}/report.md")
                report.check("saved project exports Markdown", status == 200 and markdown_text.startswith("# NYX"))
                status, envelope = api.json("GET", f"/api/projects/{project_id}/export.json")
                report.check(
                    "saved project exports a JSON envelope",
                    status == 200 and isinstance(envelope, dict) and isinstance(envelope.get("content"), str),
                )
                status, graph = api.json("GET", f"/api/projects/{project_id}/graph?view=proposed&provider=gcp")
                report.check("architecture view is projected for a provider", status == 200 and isinstance(graph, dict))
            finally:
                status, _ = api.json("DELETE", f"/api/projects/{project_id}")
                report.check("temporary project is deleted", status == 200)
                status, gone = api.json("GET", f"/api/projects/{project_id}")
                report.check(
                    "deleted project returns the NYX not-found envelope",
                    status == 404 and gone.get("error", {}).get("code") == "PROJECT_NOT_FOUND",
                )

    status, unknown = api.json("GET", "/api/does-not-exist")
    report.check(
        "unknown API path returns a JSON 404 envelope",
        status == 404 and isinstance(unknown, dict) and "error" in unknown,
    )

    total = len(report.passed) + len(report.failed)
    print()
    print(f"{len(report.passed)} of {total} checks passed against {base}.")
    return 0 if not report.failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="backend base URL (default: %(default)s)")
    args = parser.parse_args()
    try:
        return run(args.base)
    except urllib.error.URLError as error:
        print(f"FAIL  cannot reach {args.base}: {error.reason}. Start the backend first.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
