"""
api/middleware/error_handler.py
--------------------------------
Global exception handlers that convert unhandled Python exceptions into
structured JSON error responses.

Without these, FastAPI would return a plain-text 500 that leaks stack traces
to the client. We want every error to be:
  1. Logged server-side with full detail
  2. Returned to the client as a clean JSON body with an error code
  3. Never leaking internal implementation details in production
"""

import logging
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from core.config import settings

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """
    Attach all global exception handlers to the FastAPI application.

    Call this once in server.py during app construction. Each handler
    is registered for a specific exception type.

    Args:
        app: The FastAPI application instance.
    """

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """
        Handle intentionally raised HTTPExceptions (4xx/5xx from route handlers).

        These are expected errors (not found, unauthorized, etc.).
        We log at WARNING level since they're not server bugs.

        Args:
            request: Incoming HTTP request.
            exc:     The HTTPException with status_code and detail.

        Returns:
            JSONResponse: Structured error body.
        """
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        is_expected_client_miss = (
            exc.status_code == 404
            and request.url.path.startswith("/api/status/")
            and detail.get("error") == "job_not_found"
        )

        log_level = logging.INFO if is_expected_client_miss else logging.WARNING
        logger.log(
            log_level,
            "HTTP exception",
            extra={
                "status_code": exc.status_code,
                "path": request.url.path,
                "detail": exc.detail,
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)},
        )

    @app.exception_handler(ValidationError)
    async def validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
        """
        Handle Pydantic v2 ValidationErrors (malformed request bodies).

        Returns a 422 with a list of field-level validation errors so the
        client knows exactly which fields need fixing.

        Args:
            request: Incoming HTTP request.
            exc:     Pydantic ValidationError containing field errors.

        Returns:
            JSONResponse: 422 with list of validation issues.
        """
        errors = exc.errors(include_url=False)
        logger.warning(
            "Request validation failed",
            extra={"path": request.url.path, "error_count": len(errors)},
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "message": "Request body failed validation",
                "details": errors,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Catch-all handler for any unhandled exception.

        In development: include the traceback in the response for easier debugging.
        In production: return a generic 500 without leaking internal details.

        Args:
            request: Incoming HTTP request.
            exc:     Any unhandled exception.

        Returns:
            JSONResponse: 500 with safe error message.
        """
        tb = traceback.format_exc()
        logger.error(
            "Unhandled exception",
            extra={
                "path": request.url.path,
                "method": request.method,
                "error": str(exc),
                "traceback": tb,
            },
        )

        # In development, expose the traceback to speed up debugging
        body: dict = {
            "error": "internal_server_error",
            "message": "An unexpected error occurred. Please try again.",
        }
        if not settings.is_production:
            body["debug"] = {"exception": str(exc), "traceback": tb}

        return JSONResponse(status_code=500, content=body)
