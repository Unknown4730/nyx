"""NYX backend application entry point.

Responsibilities kept deliberately thin: wiring routers, CORS, startup
(initialise schema + example seed) and optional serving of the built frontend so
one container can host the whole demo.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors import register_exception_handlers
from app.api.routes import analysis, health, meta, projects
from app.config import get_settings
from app.database.project_store import get_store
from app.schemas.analysis import SCHEMA_VERSION
from app.seed import seed_example_projects

logger = logging.getLogger("nyx")


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):  # pragma: no cover - exercised by app startup
    settings = get_settings()
    _configure_logging(settings.log_level)
    # Required runtime data is validated before the service accepts traffic: a
    # missing or malformed catalogue must stop the start-up, not surface later as
    # a 500 on the first analysis.
    from app.services.cloud_catalog import get_catalog
    from app.services.templates import load_templates

    catalog = get_catalog()
    templates = load_templates()
    logger.info(
        "data loaded: catalogue %s (%d services), %d template(s)",
        catalog.version,
        len(catalog.services),
        len(templates),
    )
    store = get_store()
    logger.info("NYX %s starting (schema %s)", settings.version, SCHEMA_VERSION)
    logger.info("storage: %s", settings.db_path)
    ai = settings.ai.public_status()
    if ai["configured"]:
        logger.info("AI assist enabled via %s (model %s)", settings.ai.base_url, ai["model"])
    else:
        logger.info("AI assist disabled — deterministic rules engine will be used (%s).", ai["unavailable_reason"])
    if settings.seed_examples:
        try:
            created = seed_example_projects(store)
            if created:
                logger.info("seeded %d clearly-labelled example project(s)", created)
        except Exception as exc:  # seeding must never stop the app from booting
            logger.warning("example seeding skipped: %s", exc)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} — {settings.app_title}",
        description=(
            "NYX analyses an application description and returns a structured architecture assessment: "
            "component inventory, conventional and serverless/hybrid blueprints, AWS/Google Cloud/Azure service "
            "mappings, a rule-based serverless suitability score, architecture-level security findings, a relative "
            "cost comparison in RICU, and a migration roadmap. Generated architectures are conceptual blueprints."
        ),
        version=settings.version,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)

    api_prefix = "/api"
    app.include_router(health.router, prefix=api_prefix)
    app.include_router(meta.router, prefix=api_prefix)
    app.include_router(analysis.router, prefix=api_prefix)
    app.include_router(projects.router, prefix=api_prefix)

    @app.get("/api", include_in_schema=False)
    def api_root() -> JSONResponse:
        return JSONResponse(
            {
                "service": "NYX API",
                "version": settings.version,
                "schema_version": SCHEMA_VERSION,
                "endpoints": [
                    "GET  /api/health",
                    "GET  /api/meta",
                    "GET  /api/ai/status",
                    "POST /api/analyze",
                    "POST /api/analyze/export",
                    "GET  /api/projects",
                    "POST /api/projects",
                    "GET  /api/projects/{id}",
                    "PUT  /api/projects/{id}",
                    "DELETE /api/projects/{id}",
                    "GET  /api/projects/{id}/export.json",
                    "GET  /api/projects/{id}/report.md",
                    "GET  /api/projects/{id}/graph",
                    "GET  /api/docs",
                ],
            }
        )

    _mount_frontend(app, settings)
    return app


def _mount_frontend(app: FastAPI, settings) -> None:  # type: ignore[no-untyped-def]
    """Optional single-container mode: serve `frontend/dist` if it was built."""
    static_dir = settings.static_dir
    if not static_dir:
        return
    from pathlib import Path

    root = Path(static_dir)
    index = root / "index.html"
    if not index.exists():
        logger.warning("NYX_STATIC_DIR=%s has no index.html; skipping static hosting", static_dir)
        return

    assets = root / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        # Unknown API paths must stay JSON errors; only browser routes fall back to the app shell.
        if full_path == "api" or full_path.startswith("api/"):
            raise StarletteHTTPException(status_code=404, detail="Not Found")
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(root.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("NYX_PORT", "8000")),
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )
