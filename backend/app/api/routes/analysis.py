"""Analysis endpoints.

`POST /api/analyze` is the heart of the application.  It is deterministic by
default: the AI layer may contribute validated requirement fields only, so the
endpoint works identically with or without a provider configured.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas.analysis import AnalysisExportRequest, AnalysisRequest, AnalysisResult
from app.services.pipeline import get_pipeline
from app.services.report_generator import export_filename, to_json, to_markdown

logger = logging.getLogger("nyx.routes.analysis")

router = APIRouter(tags=["analysis"])


@router.post("/analyze", response_model=AnalysisResult)
def analyze(request: AnalysisRequest) -> AnalysisResult:
    """Run the full pipeline over the supplied requirements."""
    return get_pipeline().run(request)


@router.post("/analyze/export", response_class=JSONResponse)
def analyze_export(payload: AnalysisExportRequest) -> JSONResponse:
    """Analyse and return the report inline, without persisting anything.

    The same rules apply as to `/analyze`; only the response shape differs, which
    keeps the export path free of a second, drifting implementation.
    """
    result = get_pipeline().run(AnalysisRequest(requirements=payload.requirements, options=payload.options))
    extension = "md" if payload.format == "markdown" else "json"
    content = to_markdown(result) if payload.format == "markdown" else to_json(result)
    return JSONResponse(
        {
            "format": payload.format,
            "filename": export_filename(result, extension),
            "content": content,
        }
    )


__all__ = ["router"]
