import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ColumnElement, and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.model import EventEvidence
from signalscope.domain.events.repository import UNRESTRICTED, visible_events
from signalscope.domain.sources.model import Source
from signalscope.domain.tenancy.scope import ContentScope


class TimelineOrder(StrEnum):
    NEWEST_FIRST = "newest_first"
    OLDEST_FIRST = "oldest_first"


@dataclass(frozen=True, slots=True)
class TimelineFilters:
    # Clusters that happened at or after this time. Clusters without a time are left out.
    occurred_from: datetime | None = None
    # Clusters that happened before this time.
    occurred_to: datetime | None = None
    event_type: str | None = None
    # Clusters with at least one piece of evidence from this source.
    source_id: uuid.UUID | None = None
    # Only member events with evidence in scope are shown and counted.
    scope: ContentScope = UNRESTRICTED


@dataclass(frozen=True, slots=True)
class TimelineSource:
    source_id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    cluster_id: uuid.UUID
    event_type: str
    title: str
    occurred_at: datetime | None
    # Events in the cluster, one per report.
    event_count: int
    # Distinct sources whose documents report the cluster.
    source_count: int
    evidence_count: int
    sources: list[TimelineSource] = field(default_factory=list)


class EventTimelineService:
    """Event clusters in time order. It only reads, and never commits.

    The timeline describes what was reported. It does not rank events by
    importance. Clusters without a known time come after the dated ones, in
    either order. In a scope, a cluster appears only with a member event that
    has evidence in the scope, and its counts and sources come from that
    evidence only.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def page(
        self,
        filters: TimelineFilters,
        limit: int,
        offset: int,
        order: TimelineOrder = TimelineOrder.NEWEST_FIRST,
    ) -> tuple[list[TimelineEntry], int]:
        """One page of the timeline and how many clusters match in all."""
        conditions = _conditions(filters)
        scope = filters.scope
        occurred = (
            EventCluster.occurred_at.desc()
            if order is TimelineOrder.NEWEST_FIRST
            else EventCluster.occurred_at.asc()
        )
        rows = await self.session.execute(
            select(
                EventCluster.id,
                EventCluster.event_type,
                EventCluster.canonical_title,
                EventCluster.occurred_at,
                func.count(EventClusterMember.event_id.distinct()),
                func.count(Document.source_id.distinct()),
                func.count(EventEvidence.id.distinct()),
            )
            .join(
                EventClusterMember,
                and_(
                    EventClusterMember.cluster_id == EventCluster.id,
                    visible_events(scope, EventClusterMember.event_id),
                ),
            )
            .outerjoin(
                EventEvidence,
                and_(
                    EventEvidence.event_id == EventClusterMember.event_id,
                    scope.chunk_condition(EventEvidence.chunk_id),
                ),
            )
            .outerjoin(DocumentChunk, DocumentChunk.id == EventEvidence.chunk_id)
            .outerjoin(Document, Document.id == DocumentChunk.document_id)
            .where(*conditions)
            .group_by(EventCluster.id)
            .order_by(occurred.nulls_last(), EventCluster.created_at, EventCluster.id)
            .limit(limit)
            .offset(offset)
        )
        entries = [
            TimelineEntry(
                cluster_id=cluster_id,
                event_type=event_type,
                title=title,
                occurred_at=occurred_at,
                event_count=event_count,
                source_count=source_count,
                evidence_count=evidence_count,
            )
            for (
                cluster_id,
                event_type,
                title,
                occurred_at,
                event_count,
                source_count,
                evidence_count,
            ) in rows
        ]
        total = await self.session.scalar(
            select(func.count())
            .select_from(EventCluster)
            .where(
                *conditions,
                exists().where(
                    EventClusterMember.cluster_id == EventCluster.id,
                    visible_events(scope, EventClusterMember.event_id),
                ),
            )
        )
        sources = await self._sources([entry.cluster_id for entry in entries], scope)
        for entry in entries:
            entry.sources.extend(sources.get(entry.cluster_id, []))
        return entries, total or 0

    async def _sources(
        self, cluster_ids: list[uuid.UUID], scope: ContentScope
    ) -> dict[uuid.UUID, list[TimelineSource]]:
        if not cluster_ids:
            return {}
        rows = await self.session.execute(
            select(EventClusterMember.cluster_id, Source.id, Source.name)
            .join(EventEvidence, EventEvidence.event_id == EventClusterMember.event_id)
            .join(DocumentChunk, DocumentChunk.id == EventEvidence.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(Source, Source.id == Document.source_id)
            .where(
                EventClusterMember.cluster_id.in_(cluster_ids),
                scope.owner_condition(Source.organization_id),
            )
            .distinct()
            .order_by(EventClusterMember.cluster_id, Source.name, Source.id)
        )
        found: dict[uuid.UUID, list[TimelineSource]] = {}
        for cluster_id, source_id, name in rows:
            found.setdefault(cluster_id, []).append(TimelineSource(source_id, name))
        return found


def _conditions(filters: TimelineFilters) -> list[ColumnElement[bool]]:
    conditions = []
    if filters.event_type is not None:
        conditions.append(EventCluster.event_type == filters.event_type.strip().lower())
    if filters.occurred_from is not None:
        conditions.append(EventCluster.occurred_at >= filters.occurred_from)
    if filters.occurred_to is not None:
        conditions.append(EventCluster.occurred_at < filters.occurred_to)
    if filters.source_id is not None:
        # Aliases, so the check does not tie itself to the rows the outer query joins.
        member = aliased(EventClusterMember)
        evidence = aliased(EventEvidence)
        chunk = aliased(DocumentChunk)
        document = aliased(Document)
        conditions.append(
            exists()
            .where(member.cluster_id == EventCluster.id)
            .where(evidence.event_id == member.event_id)
            .where(chunk.id == evidence.chunk_id)
            .where(document.id == chunk.document_id)
            .where(document.source_id == filters.source_id)
        )
    return conditions
