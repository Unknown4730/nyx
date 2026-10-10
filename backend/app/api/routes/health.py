"""Health and readiness endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.config import get_settings
from app.database.project_store import get_store
from app.schemas.analysis import HealthResponse

logger = logging.getLogger("nyx.routes.health")

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Reports service liveness, AI configuration and storage state.

    Never returns a stack trace or a secret: AI status is a boolean-shaped
    summary only.
    """
    settings = get_settings()
    storage: dict[str, object] = {"backend": "sqlite", "path_kind": "configured"}
    try:
        storage = {"backend": "sqlite", "ok": True, **get_store().stats()}
    except Exception as exc:  # pragma: no cover - surfaced as degraded, not a 500
        logger.warning("storage health check failed: %s", exc)
        storage = {"backend": "sqlite", "ok": False, "error": type(exc).__name__}

    ai = settings.ai.public_status()
    degraded = not storage.get("ok")
    return HealthResponse(
        status="degraded" if degraded else "ok",
        service=settings.app_name,
        title=settings.app_title,
        tagline=settings.tagline,
        version=settings.version,
        engine_mode="deterministic_rules",
        ai={**ai, "provider": "openai-compatible" if ai["configured"] else "none"},
        storage=storage,
    )
