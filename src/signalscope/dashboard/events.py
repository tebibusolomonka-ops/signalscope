import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, Select, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import NotFoundError
from signalscope.dashboard.series import day_range, end_of, fill, start_of, utc_day
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.events.repository import visible_events
from signalscope.domain.sources.model import Source
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.domain.tenancy.scope import ContentScope


@dataclass(frozen=True, slots=True)
class EventActivityDay:
    # A UTC calendar date.
    date: date
    # Events that happened that day.
    events: int
    # Event clusters that happened that day.
    clusters: int
    # Those clusters that two or more different sources report.
    cross_source_clusters: int


class EventActivityService:
    """Daily counts of events and event clusters by when they happened. Facts only.

    Events and clusters without a known time are not in any day. In a scope,
    only events with evidence in it count, and a cluster counts when it has
    such an event; its sources are counted from sources in the scope only.
    """

    def __init__(self, session: AsyncSession, clock: Clock = utc_now) -> None:
        self.session = session
        self.clock = clock

    async def daily(
        self,
        days: int,
        event_type: str | None = None,
        source_id: uuid.UUID | None = None,
        scope: ContentScope | None = None,
    ) -> list[EventActivityDay]:
        """One entry per UTC day, oldest first, ending today, with 0 for quiet days."""
        scope = scope or ContentScope.unrestricted()
        dates = day_range(days, self.clock())
        if source_id is not None and await self.session.get(Source, source_id) is None:
            raise NotFoundError("Source was not found.")
        normalized_type = None if event_type is None else event_type.strip().lower()

        events = select(utc_day(Event.occurred_at), func.count()).where(
            *_in_range(Event.occurred_at, dates), visible_events(scope, Event.id)
        )
        if normalized_type is not None:
            events = events.where(Event.event_type == normalized_type)
        if source_id is not None:
            events = events.where(_event_from_source(Event.id, source_id))

        clusters = select(utc_day(EventCluster.occurred_at), func.count()).where(
            *_in_range(EventCluster.occurred_at, dates),
            exists().where(
                EventClusterMember.cluster_id == EventCluster.id,
                visible_events(scope, EventClusterMember.event_id),
            ),
        )
        if normalized_type is not None:
            clusters = clusters.where(EventCluster.event_type == normalized_type)
        if source_id is not None:
            clusters = clusters.where(
                exists()
                .where(EventClusterMember.cluster_id == EventCluster.id)
                .where(_event_from_source(EventClusterMember.event_id, source_id))
            )
        cross_source = clusters.where(_source_count(EventCluster.id, scope) >= 2)

        event_counts = await self._by_day(events, Event.occurred_at, dates)
        cluster_counts = await self._by_day(clusters, EventCluster.occurred_at, dates)
        cross_counts = await self._by_day(cross_source, EventCluster.occurred_at, dates)
        return [
            EventActivityDay(day, event_counts[day], cluster_counts[day], cross_counts[day])
            for day in dates
        ]

    async def _by_day(
        self, statement: Select[Any], column: Any, dates: list[date]
    ) -> dict[date, int]:
        rows = await self.session.execute(statement.group_by(utc_day(column)))
        return fill(dates, ((day, count) for day, count in rows))


def _in_range(column: Any, dates: list[date]) -> list[ColumnElement[bool]]:
    return [column >= start_of(dates[0]), column < end_of(dates[-1])]


def _event_from_source(event_id: Any, source_id: uuid.UUID) -> ColumnElement[bool]:
    """True when the event has evidence from a document of the source."""
    return (
        exists()
        .where(EventEvidence.event_id == event_id)
        .where(DocumentChunk.id == EventEvidence.chunk_id)
        .where(Document.id == DocumentChunk.document_id)
        .where(Document.source_id == source_id)
    )


def _source_count(cluster_id: Any, scope: ContentScope) -> Any:
    """How many different sources in scope report a cluster, as a correlated subquery."""
    return (
        select(func.count(Document.source_id.distinct()))
        .select_from(EventClusterMember)
        .join(EventEvidence, EventEvidence.event_id == EventClusterMember.event_id)
        .join(DocumentChunk, DocumentChunk.id == EventEvidence.chunk_id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            EventClusterMember.cluster_id == cluster_id,
            scope.source_condition(Document.source_id),
        )
        .scalar_subquery()
    )
