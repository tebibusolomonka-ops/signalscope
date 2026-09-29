import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import NotFoundError
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.events.repository import UNRESTRICTED, visible_events
from signalscope.domain.sources.model import Source
from signalscope.domain.tenancy.scope import ContentScope

# The most evidence rows a cluster detail shows. evidence_count still counts them all.
MAX_CLUSTER_EVIDENCE = 500


@dataclass(frozen=True, slots=True)
class ClusterEvidence:
    """Where one member event was reported. No document text."""

    document_id: uuid.UUID
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    confidence: float | None
    provider: str
    model: str
    chunk_metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ClusterMember:
    event_id: uuid.UUID
    title: str
    summary: str | None
    occurred_at: datetime | None
    created_at: datetime
    evidence: list[ClusterEvidence] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class EventClusterDetail:
    cluster_id: uuid.UUID
    event_type: str
    title: str
    occurred_at: datetime | None
    event_count: int
    # Distinct sources whose documents report a member event.
    source_count: int
    evidence_count: int
    # Oldest first by time, then by when they were stored. Undated events last.
    members: list[ClusterMember]


class EventClusterDetailService:
    """One event cluster with its member events and where each was reported. Read only.

    In a scope, only member events with evidence in it are shown, with that
    evidence only, and the counts describe those. A cluster with no such
    member is not found.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, cluster_id: uuid.UUID, scope: ContentScope = UNRESTRICTED
    ) -> EventClusterDetail:
        cluster = await self.session.get(EventCluster, cluster_id)
        if cluster is None:
            raise NotFoundError("Event cluster was not found.")
        events = list(
            await self.session.scalars(
                select(Event)
                .join(EventClusterMember, EventClusterMember.event_id == Event.id)
                .where(EventClusterMember.cluster_id == cluster_id, visible_events(scope, Event.id))
                .order_by(Event.occurred_at.asc().nulls_last(), Event.created_at, Event.id)
            )
        )
        if not events and not scope.is_unrestricted:
            raise NotFoundError("Event cluster was not found.")
        members = {
            event.id: ClusterMember(
                event_id=event.id,
                title=event.title,
                summary=event.summary,
                occurred_at=event.occurred_at,
                created_at=event.created_at,
            )
            for event in events
        }
        evidence_of_members = (
            select(EventEvidence, DocumentChunk.document_id, DocumentChunk.chunk_metadata, Source)
            .join(DocumentChunk, DocumentChunk.id == EventEvidence.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(Source, Source.id == Document.source_id)
            .where(
                EventEvidence.event_id.in_(list(members)),
                scope.source_condition(Document.source_id),
            )
        )
        rows = await self.session.execute(
            evidence_of_members.order_by(
                EventEvidence.event_id, DocumentChunk.document_id, DocumentChunk.position
            ).limit(MAX_CLUSTER_EVIDENCE)
        )
        for evidence, document_id, metadata, source in rows:
            members[evidence.event_id].evidence.append(
                ClusterEvidence(
                    document_id=document_id,
                    chunk_id=evidence.chunk_id,
                    source_id=source.id,
                    source_name=source.name,
                    confidence=evidence.confidence,
                    provider=evidence.provider,
                    model=evidence.model,
                    chunk_metadata=dict(metadata),
                )
            )
        evidence_count, source_count = (
            await self.session.execute(
                select(func.count(EventEvidence.id), func.count(Document.source_id.distinct()))
                .join(DocumentChunk, DocumentChunk.id == EventEvidence.chunk_id)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    EventEvidence.event_id.in_(list(members)),
                    scope.source_condition(Document.source_id),
                )
            )
        ).one()
        return EventClusterDetail(
            cluster_id=cluster.id,
            event_type=cluster.event_type,
            title=cluster.canonical_title,
            occurred_at=cluster.occurred_at,
            event_count=len(members),
            source_count=source_count,
            evidence_count=evidence_count,
            members=list(members.values()),
        )
