from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from signalscope.core.errors import (
    ConflictError,
    InvalidInputError,
    NotFoundError,
    ServiceUnavailableError,
)


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, handle_not_found)
    app.add_exception_handler(ConflictError, handle_conflict)
    app.add_exception_handler(InvalidInputError, handle_invalid_input)
    app.add_exception_handler(ServiceUnavailableError, handle_service_unavailable)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(HTTPException, handle_http_error)


async def handle_not_found(request: Request, exc: Exception) -> JSONResponse:
    return error_response(status.HTTP_404_NOT_FOUND, "not_found", str(exc))


async def handle_conflict(request: Request, exc: Exception) -> JSONResponse:
    return error_response(status.HTTP_409_CONFLICT, "conflict", str(exc))


async def handle_invalid_input(request: Request, exc: Exception) -> JSONResponse:
    return error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_input", str(exc))


async def handle_service_unavailable(request: Request, exc: Exception) -> JSONResponse:
    return error_response(status.HTTP_503_SERVICE_UNAVAILABLE, "service_unavailable", str(exc))


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    # The submitted input is left out, so rejected values are never echoed back.
    details = [
        {"loc": list(error["loc"]), "message": error["msg"], "type": error["type"]}
        for error in cast(RequestValidationError, exc).errors()
    ]
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "validation_error",
        "Request validation failed.",
        details=details,
    )


async def handle_http_error(request: Request, exc: Exception) -> JSONResponse:
    """Errors raised by routing, such as an unknown path or a wrong HTTP method."""
    http_error = cast(HTTPException, exc)
    phrase = HTTPStatus(http_error.status_code).phrase
    message = http_error.detail if isinstance(http_error.detail, str) else phrase
    return error_response(
        http_error.status_code,
        phrase.lower().replace(" ", "_"),
        message,
        headers=http_error.headers,
    )


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)
