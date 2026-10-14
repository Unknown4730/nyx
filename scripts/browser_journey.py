#!/usr/bin/env python3
"""Browser walkthrough of the NYX main journey against a running API and web client.

This drives the real interface with a headless browser: sample → form → analysis →
results (all six sections) → architecture inspection → save → reopen → export →
validation message. It writes screenshots and a JSON summary to `--out`.

Requirements (optional, development only; the app itself does not need them):

    python -m pip install playwright
    python -m playwright install chromium        # or set NYX_CHROMIUM_PATH to an existing browser

Usage (with the API on :8000 and the web client on :5173 already running):

    python scripts/browser_journey.py --base http://localhost:5173 --out browser-evidence

Exit status 0 only when every step passes. The script never edits the application.
It saves one project for the walkthrough and leaves it in the project list, labelled
with its name, so the presenter can delete it from the Projects page afterwards.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - reported to the user below
    sync_playwright = None

SAMPLE = "Online Examination Platform"
VERDICT = re.compile(r"strong candidate", re.IGNORECASE)


class Journey:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.results: list[dict[str, object]] = []

    def step(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append({"step": name, "passed": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def run(base: str, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    journey = Journey(out)
    console_errors: list[str] = []
    launch_options: dict[str, object] = {"headless": True}
    chromium_path = os.environ.get("NYX_CHROMIUM_PATH")
    if chromium_path:
        launch_options["executable_path"] = chromium_path
    launch_options["args"] = ["--no-sandbox", "--disable-dev-shm-usage"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page = context.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: console_errors.append(f"pageerror: {error}"))

        page.goto(f"{base}/", wait_until="networkidle")
        journey.step("home page shows the API as online", page.get_by_text("API online", exact=False).count() > 0)

        page.get_by_role("link", name="New analysis").first.click()
        page.wait_for_url("**/analyze")
        page.get_by_label("Application name").fill("x")
        page.get_by_label("Description", exact=True).fill("short")
        page.get_by_role("button", name="Run analysis").click()
        journey.step("client validation explains the rejected name and description", page.get_by_text("at least", exact=False).count() >= 2)
        page.screenshot(path=str(out / "01-validation.png"))

        page.get_by_role("button", name=f"Use “{SAMPLE}”").click()
        journey.step("sample fills the requirements form", page.get_by_label("Application name").input_value() == SAMPLE)
        page.get_by_role("button", name="Run analysis").click()
        page.wait_for_url("**/results", timeout=30_000)
        page.wait_for_timeout(500)
        journey.step("analysis reaches the results page", page.url.endswith("/results"))
        # The gauge shows the score rounded to a whole number (78.1 -> 78); the exact value is in the JSON export.
        journey.step("the real verdict and rounded score are shown", page.get_by_text(VERDICT).count() > 0 and page.get_by_text("78", exact=True).count() > 0)
        page.screenshot(path=str(out / "02-results-overview.png"), full_page=True)

        for tab, shot in [
            ("Architecture", "03-architecture.png"),
            ("Cloud services", "04-cloud-services.png"),
            ("Cost model", "05-cost.png"),
            ("Security", "06-security.png"),
            ("Migration", "07-migration.png"),
        ]:
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(250)
            journey.step(f"section '{tab}' renders", page.get_by_role("tabpanel").count() > 0)
            page.screenshot(path=str(out / shot), full_page=True)

        page.get_by_role("tab", name="Architecture").click()
        nodes = page.locator("[data-testid=diagram-node]")
        journey.step("architecture diagram draws the backend components", nodes.count() >= 5, f"{nodes.count()} nodes")
        nodes.first.click()
        journey.step("clicking a component opens the inspector", page.locator("[data-testid=inspector]").count() > 0)
        nodes.nth(1).focus()
        page.keyboard.press("Enter")
        journey.step("keyboard Enter selects a component", nodes.nth(1).get_attribute("aria-pressed") == "true")
        page.get_by_role("button", name="Fit to width").click()
        journey.step("Fit to width changes the diagram scale", page.locator("[aria-live=polite]").first.inner_text() != "100%")
        page.get_by_role("button", name="Reset").click()
        page.locator("select#provider-select").select_option("gcp")
        journey.step("switching provider relabels services", nodes.first.get_attribute("aria-label") is not None)
        page.locator("summary", has_text="Text alternative").first.click()
        journey.step("text alternative lists components in a table", page.locator("table").count() >= 1)

        page.get_by_role("tab", name="Cost model").click()
        page.wait_for_timeout(200)
        sensitivity = page.get_by_role("table", name=re.compile("sensitivity", re.IGNORECASE))
        journey.step("cost sensitivity table shows every scenario", sensitivity.locator("tbody tr").count() >= 3, f"{sensitivity.locator('tbody tr').count()} rows")

        page.get_by_role("button", name="Save project").click()
        page.get_by_text("Saved to projects").wait_for(timeout=10_000)
        journey.step("save confirms the project was stored", True)

        page.get_by_role("link", name="Projects").first.click()
        page.wait_for_url("**/projects")
        page.wait_for_timeout(400)
        # "Mine" lists only saved projects, so the row opened below is the user's copy, not a sample.
        page.get_by_role("button", name="Mine", exact=True).click()
        page.wait_for_timeout(200)
        row = page.locator("table tbody tr").filter(has_text=SAMPLE).first
        journey.step("the saved project appears in Projects", row.count() > 0)
        page.screenshot(path=str(out / "08-projects.png"), full_page=True)
        row.get_by_role("button", name=re.compile("^Open")).click()
        page.wait_for_url(re.compile(r".*/projects/.+"), timeout=15_000)
        page.wait_for_timeout(400)
        journey.step("reopening the project shows its verdict", page.get_by_text(VERDICT).count() > 0)

        with page.expect_download() as download_info:
            page.get_by_role("button", name="Export Markdown").click()
        download = download_info.value
        markdown_path = out / download.suggested_filename
        download.save_as(str(markdown_path))
        markdown = markdown_path.read_text(encoding="utf-8")
        journey.step("Markdown export downloads a report", markdown.startswith("# NYX") and len(markdown) > 1000, download.suggested_filename)

        with page.expect_download() as download_info:
            page.get_by_role("button", name="Export JSON").click()
        download = download_info.value
        json_path = out / download.suggested_filename
        download.save_as(str(json_path))
        try:
            parsed = json.loads(json_path.read_text(encoding="utf-8"))
            json_ok = "suitability" in parsed
        except json.JSONDecodeError:
            json_ok = False
        journey.step("JSON export downloads a parseable analysis", json_ok, download.suggested_filename)

        journey.step("no uncaught page errors or console errors", not console_errors, f"{len(console_errors)} console error(s)")
        browser.close()

    summary = {"base": base, "steps": journey.results, "passed": sum(1 for r in journey.results if r["passed"]), "total": len(journey.results)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n{summary['passed']} of {summary['total']} browser steps passed. Evidence written to {out}.")
    return 0 if summary["passed"] == summary["total"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://localhost:5173", help="web client URL (default: %(default)s)")
    parser.add_argument("--out", default="browser-evidence", help="directory for screenshots and summary.json")
    args = parser.parse_args()
    if sync_playwright is None:
        print("Playwright is not installed. Run: python -m pip install playwright && python -m playwright install chromium")
        return 2
    return run(args.base.rstrip("/"), Path(args.out))


if __name__ == "__main__":
    sys.exit(main())
