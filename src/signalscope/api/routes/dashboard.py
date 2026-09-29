import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import StringConstraints

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.tenancy import Policy, ReadScope
from signalscope.dashboard.events import EventActivityService
from signalscope.dashboard.overview import DashboardOverviewService
from signalscope.dashboard.schemas import (
    DashboardOverviewRead,
    EventActivityDayRead,
    EventActivityRead,
    SourceActivityDayRead,
    SourceActivityRead,
)
from signalscope.dashboard.series import MAX_DAYS, MIN_DAYS
from signalscope.dashboard.sources import SourceActivityService
from signalscope.domain.events.model import EVENT_TYPE_MAX_LENGTH

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

DEFAULT_DAYS = 30

Days = Annotated[
    int, Query(ge=MIN_DAYS, le=MAX_DAYS, description="How many UTC days, ending today.")
]
TypeQuery = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=EVENT_TYPE_MAX_LENGTH),
    Query(description="The event type, such as flood. Case does not matter."),
]


@router.get("/overview")
async def dashboard_overview(session: DatabaseSession, scope: ReadScope) -> DashboardOverviewRead:
    """How many records of each kind exist, and how many jobs are waiting or running.

    Aggregate counts only. There are no scores, rankings or judgements. With
    authentication on, every count covers the organization_id organization
    only; there is no view across organizations.
    """
    overview = await DashboardOverviewService(session).overview(scope)
    return DashboardOverviewRead.model_validate(overview)


@router.get("/sources")
async def dashboard_sources(
    session: DatabaseSession,
    scope: ReadScope,
    policy: Policy,
    days: Days = DEFAULT_DAYS,
    source_id: uuid.UUID | None = None,
) -> SourceActivityRead:
    """Documents stored and published per UTC day, for all sources in scope or one."""
    await policy.check_source_filter(source_id)
    items = await SourceActivityService(session).daily(days, source_id, scope)
    return SourceActivityRead(
        days=days,
        source_id=source_id,
        items=[SourceActivityDayRead.model_validate(item) for item in items],
    )


@router.get("/events")
async def dashboard_events(
    session: DatabaseSession,
    scope: ReadScope,
    policy: Policy,
    days: Days = DEFAULT_DAYS,
    event_type: TypeQuery = None,
    source_id: uuid.UUID | None = None,
) -> EventActivityRead:
    """Events and event clusters per UTC day, by when they happened.

    cross_source_clusters counts the clusters that two or more sources report.
    Undated events are not counted. With authentication on, only the
    organization_id organization's events and sources count.
    """
    await policy.check_source_filter(source_id)
    items = await EventActivityService(session).daily(days, event_type, source_id, scope)
    return EventActivityRead(
        days=days,
        event_type=event_type,
        source_id=source_id,
        items=[EventActivityDayRead.model_validate(item) for item in items],
    )
