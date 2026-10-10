"""Shared fixtures for the NYX backend test suite.

Tests never touch the repository database: each session gets a temporary
SQLite file, and AI assist is disabled unless a test opts in with a stub
provider.  Nothing here performs a network request.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _environment(tmp_path_factory: pytest.TempPathFactory):
    directory = tmp_path_factory.mktemp("nyx-data")
    os.environ["NYX_DB_PATH"] = str(directory / "test.sqlite3")
    os.environ["NYX_SEED_EXAMPLES"] = "0"
    os.environ["NYX_ENV"] = "test"
    os.environ["NYX_LOG_LEVEL"] = "WARNING"
    for name in ("NYX_AI_BASE_URL", "NYX_AI_API_KEY", "NYX_AI_MODEL"):
        os.environ.pop(name, None)
    os.environ["NYX_AI_ENABLED"] = "0"

    from app.config import get_settings

    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture()
def store(tmp_path: Path):
    from app.database.project_store import ProjectStore, reset_store_for_tests

    instance = ProjectStore(str(tmp_path / "projects.sqlite3"))
    reset_store_for_tests(instance)
    yield instance
    reset_store_for_tests(None)
    instance.close()


@pytest.fixture()
def client(store, _environment):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def requirements_factory():
    from app.schemas.requirements import ApplicationRequirements

    def build(**overrides):
        payload = {
            "name": "Test Application",
            "description": (
                "An internal tool for 400 staff that processes uploads and generates monthly PDF reports; "
                "usage peaks at the end of each month."
            ),
        }
        payload.update(overrides)
        return ApplicationRequirements(**payload)

    return build


@pytest.fixture()
def analysis_payload(requirements_factory):
    def build(**overrides):
        payload = {"requirements": requirements_factory(**overrides).model_dump(mode="json")}
        return payload

    return build


@pytest.fixture()
def run_pipeline(_environment):
    from app.services.pipeline import AnalysisPipeline

    def run(requirements, *, use_ai: bool = False, provider=None, **option_overrides):
        from app.schemas.analysis import AnalysisOptions, AnalysisRequest

        pipeline = AnalysisPipeline(ai_provider=provider)
        request = AnalysisRequest(
            requirements=requirements,
            options=AnalysisOptions(use_ai=use_ai, **option_overrides),
        )
        return pipeline.run(request)

    return run


def load_template(name: str):
    from app.services.templates import requirements_for

    value = requirements_for(name)
    assert value is not None, f"unknown template {name}"
    return value
