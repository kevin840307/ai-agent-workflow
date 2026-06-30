from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.workflow_runtime.error_codes import classify_exception


def error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "detail": message,
    }


def _from_detail(status_code: int, detail: Any) -> tuple[str, str, dict[str, Any]]:
    if isinstance(detail, dict):
        code = str(detail.get("code") or f"HTTP_{status_code}")
        message = str(detail.get("message") or detail.get("detail") or "Request failed")
        details = detail.get("details") if isinstance(detail.get("details"), dict) else {}
        return code, message, details
    message = str(detail or "Request failed")
    code = classify_exception(message)
    if code == "WORKFLOW_FAILED":
        code = f"HTTP_{status_code}"
    return code, message, {}


async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message, details = _from_detail(exc.status_code, exc.detail)
    return JSONResponse(status_code=exc.status_code, content=error_payload(code, message, details))


async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_payload(
            "VALIDATION_ERROR",
            "Request validation failed.",
            {"errors": exc.errors()},
        ),
    )
