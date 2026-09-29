import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, StringConstraints

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.api.tenancy import Policy, ReadScope
from signalscope.core.errors import InvalidInputError
from signalscope.domain.events.model import EVENT_TYPE_MAX_LENGTH
from signalscope.domain.events.schemas import TimelineItemRead, TimelineSourceRead
from signalscope.domain.events.timeline import EventTimelineService, TimelineFilters, TimelineOrder

router = APIRouter(prefix="/timeline", tags=["Timeline"])

TypeQuery = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=EVENT_TYPE_MAX_LENGTH),
    Query(description="The event type, such as flood. Case does not matter."),
]
TimeQuery = Annotated[AwareDatetime | None, Query(description="A time with a time zone.")]


@router.get("")
async def event_timeline(
    session: DatabaseSession,
    page: Pagination,
    scope: ReadScope,
    policy: Policy,
    occurred_from: TimeQuery = None,
    occurred_to: TimeQuery = None,
    event_type: TypeQuery = None,
    source_id: uuid.UUID | None = None,
    order: TimelineOrder = TimelineOrder.NEWEST_FIRST,
) -> Page[TimelineItemRead]:
    """Linked events in time order, newest first unless order says otherwise.

    Each item is one cluster of events that report the same thing, with how
    many events, sources and evidence rows back it. Items without a known time
    come last. With occurred_from or occurred_to, they are left out. source_id
    keeps the clusters that source reports. The timeline only describes what
    was reported: it does not rank events by importance. With authentication on,
    only clusters with evidence in the organization_id organization, counted
    from that evidence only.
    """
    await policy.check_source_filter(source_id)
    if occurred_from is not None and occurred_to is not None and occurred_from >= occurred_to:
        raise InvalidInputError("occurred_from must be before occurred_to.")
    entries, total = await EventTimelineService(session).page(
        TimelineFilters(occurred_from, occurred_to, event_type, source_id, scope),
        page.limit,
        page.offset,
        order,
    )
    return Page[TimelineItemRead](
        items=[
            TimelineItemRead(
                cluster_id=entry.cluster_id,
                event_type=entry.event_type,
                title=entry.title,
                occurred_at=entry.occurred_at,
                event_count=entry.event_count,
                source_count=entry.source_count,
                evidence_count=entry.evidence_count,
                sources=[
                    TimelineSourceRead(source_id=source.source_id, name=source.name)
                    for source in entry.sources
                ],
            )
            for entry in entries
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
