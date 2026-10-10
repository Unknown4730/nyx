"""Saved-project endpoints.

A project stores the *whole* validated analysis result as JSON plus the summary
columns needed for listing, so reopening a project reproduces exactly what the
user saw — including the architecture graph, after a restart.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from app.database.project_store import ProjectStore, get_store
from app.schemas.analysis import (
    AnalysisOptions,
    AnalysisRequest,
    ProjectCreateRequest,
    ProjectDetail,
    ProjectSummary,
    ProjectUpdateRequest,
)
from app.schemas.common import CloudProvider, ProjectKind
from app.services.pipeline import get_pipeline
from app.services.report_generator import to_json, to_markdown

logger = logging.getLogger("nyx.routes.projects")

router = APIRouter(tags=["projects"])


def _store() -> ProjectStore:
    return get_store()


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    kind: ProjectKind | None = Query(default=None),
) -> list[ProjectSummary]:
    return _store().list(limit=limit, offset=offset, kind=kind.value if kind else None)


@router.get("/projects/stats")
def project_stats() -> dict[str, Any]:
    """Aggregated counters for the dashboard — derived from stored rows only."""
    store = _store()
    stats = store.stats()
    recent = store.list(limit=6)
    return {**stats, "recent": [item.model_dump(mode="json") for item in recent]}


@router.post("/projects", response_model=ProjectDetail, status_code=201)
def create_project(payload: ProjectCreateRequest) -> ProjectDetail:
    """Persist a new analysis.

    The request carries requirements (and optionally a client-side result the
    user already has).  When a result is supplied it is re-validated and, if it
    does not match the requirements, re-analysed server-side rather than being
    trusted blindly.
    """
    store = _store()
    request = AnalysisRequest(requirements=payload.requirements, options=payload.options)
    if payload.result:
        try:
            from app.schemas.analysis import AnalysisResult

            stored = AnalysisResult.model_validate(payload.result)
            if stored.analysis_id and stored.application.description == request.requirements.description:
                return store.create(payload, stored)
            logger.info("client result did not match requirements; re-analysing server-side")
        except Exception as exc:
            logger.info("client result rejected by schema validation (%s); re-analysing", type(exc).__name__)
    result = get_pipeline().run(request)
    return store.create(payload, result)


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str) -> ProjectDetail:
    return _store().get(project_id)


@router.put("/projects/{project_id}", response_model=ProjectDetail)
def update_project(project_id: str, payload: ProjectUpdateRequest) -> ProjectDetail:
    store = _store()
    if payload.requirements is not None or payload.reanalyze:
        current = store.get(project_id)
        requirements = payload.requirements or current.result.application
        result = get_pipeline().run(
            AnalysisRequest(
                requirements=requirements,
                options=AnalysisOptions(
                    use_ai=current.result.engine_mode.value == "ai_assisted",
                    providers=current.result.providers or [CloudProvider.AWS, CloudProvider.GCP, CloudProvider.AZURE],
                    default_provider=current.result.default_provider,
                ),
            )
        )
        updated = store.replace_result(project_id, result)
        if payload.name or payload.notes is not None:
            updated = store.update(project_id, name=payload.name, notes=payload.notes)
        return updated
    return store.update(project_id, name=payload.name, notes=payload.notes)


@router.delete("/projects/{project_id}", status_code=200)
def delete_project(project_id: str) -> dict[str, Any]:
    deleted = _store().delete(project_id)
    if not deleted:
        from app.database.project_store import ProjectNotFound

        raise ProjectNotFound(project_id)
    return {"deleted": True, "id": project_id}


@router.get("/projects/{project_id}/export.json")
def export_json(project_id: str) -> JSONResponse:
    result = _store().get(project_id).result
    content = to_json(result)
    return JSONResponse(
        content={"filename": _filename(project_id, "json"), "format": "json", "content": content},
        headers={"Content-Disposition": f'attachment; filename="nyx-{project_id}.json"'},
    )


@router.get("/projects/{project_id}/report.md", response_class=PlainTextResponse)
def export_markdown(project_id: str) -> PlainTextResponse:
    result = _store().get(project_id).result
    return PlainTextResponse(
        to_markdown(result),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="nyx-{project_id}.md"'},
    )


@router.get("/projects/{project_id}/graph")
def project_graph(
    project_id: str,
    view: str = Query(default="proposed", pattern="^(conventional|proposed)$"),
    provider: str = Query(default="aws", pattern="^(aws|gcp|azure)$"),
) -> dict[str, Any]:
    """Project the stored analysis into the exact graph + labels for one view."""
    result = _store().get(project_id).result
    graph = result.architecture(view)
    if graph is None:
        return {"error": "unknown view", "available": result.available_views}
    return {
        "view": graph.id,
        "style": graph.style.value,
        "title": graph.title,
        "summary": graph.summary,
        "provider": provider,
        "nodes": [
            {
                "id": component.id,
                "label": component.label,
                "type": component.type.value,
                "tier": component.tier.value,
                "description": component.description,
                "deployment_target": component.deployment_target.value,
                "service": (component.mappings.get(provider).service_name if component.mappings.get(provider) else None),
                "service_class": (
                    component.mappings.get(provider).serverless_class if component.mappings.get(provider) else None
                ),
                "position": graph.layout[component.id].model_dump() if component.id in graph.layout else {"x": 0, "y": 0},
                "traits": component.traits.model_dump(mode="json"),
                "warnings": component.warnings,
                "assumptions": component.assumptions,
                "properties": component.properties,
            }
            for component in graph.components
        ],
        "edges": [
            connection.model_dump(mode="json") for connection in graph.connections
        ],
        "caveats": graph.caveats,
    }


def _filename(project_id: str, extension: str) -> str:
    return f"nyx-report-{project_id}.{extension}"
