import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, exists, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.sources.model import Source
from signalscope.domain.tenancy.scope import ContentScope

# The most evidence rows an event detail shows.
MAX_DETAIL_EVIDENCE = 100
UNRESTRICTED = ContentScope.unrestricted()


def visible_events(scope: ContentScope, event_id: Any) -> ColumnElement[bool]:
    """Events with at least one piece of evidence in scope.

    Events have no organization of their own; their evidence chunks say
    whose they are.
    """
    if scope.is_unrestricted:
        return true()
    visible = (
        select(EventEvidence.event_id)
        .where(scope.chunk_condition(EventEvidence.chunk_id))
        .correlate(None)
    )
    return event_id.in_(visible)  # type: ignore[no-any-return]


@dataclass(frozen=True, slots=True)
class EventFilters:
    event_type: str | None = None
    # Events that happened at or after this time. Events without a time are left out.
    occurred_from: datetime | None = None
    # Events that happened before this time.
    occurred_to: datetime | None = None
    scope: ContentScope = UNRESTRICTED


@dataclass(frozen=True, slots=True)
class EvidenceWithChunk:
    evidence: EventEvidence
    document_id: uuid.UUID
    # Where the chunk came from, such as {"page_number": 3}.
    chunk_metadata: dict[str, Any]
    document_title: str | None
    source_id: uuid.UUID
    source_name: str


class EventRepository:
    """Access to events and their evidence. It never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_page(
        self, filters: EventFilters, limit: int, offset: int
    ) -> tuple[list[Event], int]:
        """Events in time order. Events without a known time come last."""
        conditions = _conditions(filters)
        events = await self.session.scalars(
            select(Event)
            .where(*conditions)
            .order_by(Event.occurred_at.asc().nulls_last(), Event.created_at, Event.id)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(Event).where(*conditions)
        )
        return list(events), total or 0

    async def delete_orphaned_events(self, event_ids: Collection[uuid.UUID] | None = None) -> int:
        """Delete events that no evidence points to any more, and return how many.

        Evidence goes away with its chunk, so this runs after chunks are
        replaced or deleted. event_ids limits the check to those events. When
        events are deleted, clusters left without members are deleted too.
        """
        statement = delete(Event).where(~exists().where(EventEvidence.event_id == Event.id))
        if event_ids is not None:
            if not event_ids:
                return 0
            statement = statement.where(Event.id.in_(event_ids))
        deleted = len((await self.session.execute(statement.returning(Event.id))).all())
        if deleted:
            await self.delete_empty_clusters()
        return deleted

    async def delete_empty_clusters(self) -> int:
        """Delete event clusters that no event belongs to any more, and return how many."""
        result = await self.session.execute(
            delete(EventCluster)
            .where(~exists().where(EventClusterMember.cluster_id == EventCluster.id))
            .returning(EventCluster.id)
        )
        return len(result.all())

    async def get(self, event_id: uuid.UUID) -> Event | None:
        return await self.session.get(Event, event_id)

    async def evidence(
        self,
        event_id: uuid.UUID,
        limit: int = MAX_DETAIL_EVIDENCE,
        scope: ContentScope = UNRESTRICTED,
    ) -> list[EvidenceWithChunk]:
        rows = await self.session.execute(
            select(
                EventEvidence,
                DocumentChunk.document_id,
                DocumentChunk.chunk_metadata,
                Document.title,
                Source.id,
                Source.name,
            )
            .join(DocumentChunk, DocumentChunk.id == EventEvidence.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(Source, Source.id == Document.source_id)
            .where(
                EventEvidence.event_id == event_id,
                scope.chunk_condition(EventEvidence.chunk_id),
            )
            .order_by(DocumentChunk.document_id, DocumentChunk.position, EventEvidence.id)
            .limit(limit)
        )
        return [
            EvidenceWithChunk(evidence, document_id, dict(metadata), title, source_id, source_name)
            for evidence, document_id, metadata, title, source_id, source_name in rows
        ]


def _conditions(filters: EventFilters) -> list[ColumnElement[bool]]:
    conditions = [visible_events(filters.scope, Event.id)]
    if filters.event_type is not None:
        conditions.append(Event.event_type == filters.event_type.strip().lower())
    if filters.occurred_from is not None:
        conditions.append(Event.occurred_at >= filters.occurred_from)
    if filters.occurred_to is not None:
        conditions.append(Event.occurred_at < filters.occurred_to)
    return conditions
