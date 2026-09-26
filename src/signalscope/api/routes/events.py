import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, StringConstraints

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.core.errors import InvalidInputError, NotFoundError
from signalscope.domain.events.model import EVENT_TYPE_MAX_LENGTH
from signalscope.domain.events.repository import EventFilters, EventRepository
from signalscope.domain.events.schemas import EventDetailRead, EventEvidenceRead, EventRead

router = APIRouter(prefix="/events", tags=["Events"])

TypeQuery = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=EVENT_TYPE_MAX_LENGTH),
    Query(description="The event type, such as flood. Case does not matter."),
]
TimeQuery = Annotated[AwareDatetime | None, Query(description="A time with a time zone.")]


@router.get("")
async def list_events(
    session: DatabaseSession,
    page: Pagination,
    event_type: TypeQuery = None,
    occurred_from: TimeQuery = None,
    occurred_to: TimeQuery = None,
) -> Page[EventRead]:
    """List events found in documents, in time order. Events are read only.

    With occurred_from or occurred_to, events without a known time are left out.
    """
    if occurred_from is not None and occurred_to is not None and occurred_from >= occurred_to:
        raise InvalidInputError("occurred_from must be before occurred_to.")
    events, total = await EventRepository(session).list_page(
        EventFilters(event_type, occurred_from, occurred_to), page.limit, page.offset
    )
    return Page[EventRead](
        items=[EventRead.model_validate(event) for event in events],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{event_id}")
async def get_event(event_id: uuid.UUID, session: DatabaseSession) -> EventDetailRead:
    """One event with the chunks that report it, the first 100 in document order."""
    repository = EventRepository(session)
    event = await repository.get(event_id)
    if event is None:
        raise NotFoundError("Event was not found.")
    evidence = await repository.evidence(event_id)
    return EventDetailRead(
        event=EventRead.model_validate(event),
        evidence=[
            EventEvidenceRead(
                document_id=item.document_id,
                chunk_id=item.evidence.chunk_id,
                confidence=item.evidence.confidence,
                provider=item.evidence.provider,
                model=item.evidence.model,
                chunk_metadata=item.chunk_metadata,
            )
            for item in evidence
        ],
    )
