from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from signalscope.core.errors import ConflictError, NotFoundError, ServiceUnavailableError


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, handle_not_found)
    app.add_exception_handler(ConflictError, handle_conflict)
    app.add_exception_handler(ServiceUnavailableError, handle_service_unavailable)


async def handle_not_found(request: Request, exc: Exception) -> JSONResponse:
    return error_response(status.HTTP_404_NOT_FOUND, "not_found", str(exc))


async def handle_conflict(request: Request, exc: Exception) -> JSONResponse:
    return error_response(status.HTTP_409_CONFLICT, "conflict", str(exc))


async def handle_service_unavailable(request: Request, exc: Exception) -> JSONResponse:
    return error_response(status.HTTP_503_SERVICE_UNAVAILABLE, "service_unavailable", str(exc))


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )
