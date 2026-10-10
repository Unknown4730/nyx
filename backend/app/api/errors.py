"""Consistent API error envelope and exception wiring."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database.project_store import ProjectNotFound
from app.schemas.analysis import ApiError, ErrorResponse

logger = logging.getLogger("nyx.api")

MAX_DETAIL_ITEMS = 8


def api_error(
    code: str,
    message: str,
    *,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    details: list[str] | None = None,
    retryable: bool = False,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ApiError(code=code, message=message, details=(details or [])[:MAX_DETAIL_ITEMS], retryable=retryable)
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def _validation_details(exc: RequestValidationError | ValidationError) -> list[str]:
    raw = getattr(exc, "errors", None)
    items = raw() if callable(raw) else []
    details: list[str] = []
    for item in items[:MAX_DETAIL_ITEMS]:
        location = ".".join(str(part) for part in item.get("loc", []) if part not in {"body"})
        message = str(item.get("msg", "invalid value"))
        kind = str(item.get("type", ""))
        details.append(f"{location or 'body'}: {message} ({kind})" if location else f"{message} ({kind})")
    if len(items) > MAX_DETAIL_ITEMS:
        details.append(f"…and {len(items) - MAX_DETAIL_ITEMS} further validation issue(s).")
    return details


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return api_error(
            "INVALID_REQUEST",
            "The request body did not satisfy the analysis request schema.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=_validation_details(exc),
        )

    @app.exception_handler(ValidationError)
    async def _handle_model_validation(request: Request, exc: ValidationError) -> JSONResponse:
        logger.warning("outbound schema validation failed for %s: %s", request.url.path, exc)
        return api_error(
            "SCHEMA_MISMATCH",
            "The analysis result failed internal schema validation and was not returned.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=_validation_details(exc),
        )

    @app.exception_handler(ProjectNotFound)
    async def _handle_not_found(request: Request, exc: ProjectNotFound) -> JSONResponse:
        return api_error(
            "PROJECT_NOT_FOUND",
            "No saved project exists with that identifier.",
            status_code=status.HTTP_404_NOT_FOUND,
            details=[f"id={getattr(exc, 'args', [''])[0]!r}"],
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        # Never leak internals: unexpected errors arrive here without a message we control.
        return api_error(f"HTTP_{exc.status_code}", detail, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover - last resort
        logger.exception("unhandled error while serving %s", request.url.path)
        return api_error(
            "INTERNAL_ERROR",
            "NYX could not complete this request. The server log contains the details.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            retryable=True,
        )
