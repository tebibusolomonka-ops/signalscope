from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from signalscope.api.dependencies import Blobs, DatabaseSession
from signalscope.domain.diagnostics.readiness import (
    ComponentState,
    DependencyReadinessService,
    ReadinessReport,
)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ComponentReadinessResponse(BaseModel):
    name: str
    state: ComponentState
    required: bool
    detail: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    components: list[ComponentReadinessResponse]


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/live")
async def live() -> HealthResponse:
    """Process-level liveness. It needs no database and answers even if it is down."""
    return HealthResponse(status="ok")


@router.get("/health/ready")
async def ready(
    session: DatabaseSession, blobs: Blobs, request: Request, response: Response
) -> ReadinessResponse:
    """Dependency readiness. Answers 503 when a required dependency is unavailable."""
    report = await DependencyReadinessService(session, request.app.state.settings, blobs).check()
    if not report.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return _to_response(report)


def _to_response(report: ReadinessReport) -> ReadinessResponse:
    return ReadinessResponse(
        status="ready" if report.ready else "unavailable",
        components=[
            ComponentReadinessResponse(
                name=component.name,
                state=component.state,
                required=component.required,
                detail=component.detail,
            )
            for component in report.components
        ],
    )
