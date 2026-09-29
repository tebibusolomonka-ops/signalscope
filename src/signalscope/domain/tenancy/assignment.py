import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.linking import EventLinkingService, refresh_canonical_values
from signalscope.domain.events.model import EventEvidence
from signalscope.domain.events.repository import EventRepository
from signalscope.domain.organizations.model import Organization
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.sources.model import Source


@dataclass(frozen=True, slots=True)
class SourceAssignment:
    source_id: uuid.UUID
    organization_id: uuid.UUID
    documents: int
    events_relinked: int
    research_sessions: int


class LegacySourceAssignmentService:
    """Moves one legacy source, with everything made from it, into an organization.

    Only a source without an organization can be assigned, once. Moving a
    source between organizations, or back to legacy, is not supported.

    One transaction sets the owner, takes the source's events out of their
    legacy clusters (deleting clusters left empty), and gives the source's
    legacy research sessions the same organization, since they only search
    that source. Sessions without a source and investigations are not
    touched. After the commit the events are linked again, into clusters of
    the new organization; an event that fails to link stays unclustered, and
    link-events can link it later.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def assign(self, source_id: uuid.UUID, organization_id: uuid.UUID) -> SourceAssignment:
        async with self.session_factory() as session:
            try:
                documents, events, research_sessions = await self._move(
                    session, source_id, organization_id
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        linker = EventLinkingService(self.session_factory)
        relinked = 0
        for event_id in events:
            if await linker.link_event(event_id) is not None:
                relinked += 1
        return SourceAssignment(source_id, organization_id, documents, relinked, research_sessions)

    async def _move(
        self, session: AsyncSession, source_id: uuid.UUID, organization_id: uuid.UUID
    ) -> tuple[int, list[uuid.UUID], int]:
        source = await session.get(Source, source_id, with_for_update=True, populate_existing=True)
        if source is None:
            raise NotFoundError("Source was not found.")
        if source.organization_id is not None:
            raise ConflictError("The source already belongs to an organization.")
        if await session.get(Organization, organization_id) is None:
            raise NotFoundError("Organization was not found.")

        documents = await session.scalar(
            select(func.count()).select_from(Document).where(Document.source_id == source_id)
        )
        events = list(
            await session.scalars(
                select(EventEvidence.event_id)
                .distinct()
                .join(DocumentChunk, DocumentChunk.id == EventEvidence.chunk_id)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(Document.source_id == source_id)
            )
        )
        if events:
            clusters = list(
                await session.scalars(
                    delete(EventClusterMember)
                    .where(EventClusterMember.event_id.in_(events))
                    .returning(EventClusterMember.cluster_id)
                )
            )
            await EventRepository(session).delete_empty_clusters()
            # Clusters that keep other legacy events get their title and time again.
            for cluster in await session.scalars(
                select(EventCluster).where(EventCluster.id.in_(set(clusters)))
            ):
                await refresh_canonical_values(session, cluster)

        source.organization_id = organization_id
        assigned = await session.execute(
            update(ResearchSession)
            .where(
                ResearchSession.source_id == source_id, ResearchSession.organization_id.is_(None)
            )
            .values(organization_id=organization_id)
            .execution_options(synchronize_session=False)
        )
        return documents or 0, events, int(assigned.rowcount)  # type: ignore[attr-defined]
