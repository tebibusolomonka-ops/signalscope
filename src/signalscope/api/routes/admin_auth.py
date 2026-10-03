from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.domain.users.throttle_administration import LoginThrottleAdministrationService

router = APIRouter(prefix="/admin/auth", tags=["Authentication administration"])


class LoginThrottleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    identifier: str
    failure_count: int
    window_started_at: datetime
    blocked_until: datetime | None
    updated_at: datetime


def administration(
    current: CurrentSession, session: DatabaseSession
) -> LoginThrottleAdministrationService:
    return LoginThrottleAdministrationService(session, current.user)


Administration = Annotated[LoginThrottleAdministrationService, Depends(administration)]


@router.get("/throttles")
async def list_login_throttles(
    service: Administration, page: Pagination
) -> Page[LoginThrottleRead]:
    throttles, total = await service.list_throttles(limit=page.limit, offset=page.offset)
    return Page[LoginThrottleRead](
        items=[LoginThrottleRead.model_validate(item) for item in throttles],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.delete("/throttles/{identifier}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_login_throttle(identifier: str, service: Administration) -> None:
    await service.clear(identifier)
