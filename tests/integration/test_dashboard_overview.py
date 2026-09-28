from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.dashboard.overview import DashboardOverview, DashboardOverviewService
from signalscope.domain.claims.job import ClaimExtractionJob, ClaimExtractionJobStatus
from signalscope.domain.claims.model import Claim
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.entities.job import EntityExtractionJob, EntityExtractionJobStatus
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.ingestion.model import IngestionJob, IngestionJobStatus, IngestionRun
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


async def overview(session_factory: async_sessionmaker[AsyncSession]) -> DashboardOverview:
    async with session_factory() as session:
        return await DashboardOverviewService(session).overview()


async def test_empty_database(session_factory: async_sessionmaker[AsyncSession]) -> None:
    found = await overview(session_factory)

    assert found == DashboardOverview(*([0] * 15))


async def test_record_counts(session_factory: async_sessionmaker[AsyncSession]) -> None:
    wire = await create_source(session_factory, "Wire")
    await create_source(session_factory, "Paper")
    await report_event(session_factory, wire, "Harbour flood", evidence_count=2)
    await report_event(session_factory, wire, "Harbour flood")
    await report_event(session_factory, wire, "Bridge closed", event_type="closure")
    await EventLinkingService(session_factory).link_unclustered()
    async with session_factory() as session:
        session.add_all(
            [
                Entity(canonical_name="Porto", normalized_name="porto", entity_type="city"),
                Claim(text="Prices rose", normalized_text="prices rose", claim_type="statistic"),
                ResearchSession(),
                Investigation(title="Floods"),
                Investigation(title="Prices"),
            ]
        )
        await session.commit()

    found = await overview(session_factory)

    assert (found.sources, found.documents, found.chunks) == (2, 3, 4)
    assert (found.entities, found.claims, found.events, found.event_clusters) == (1, 1, 3, 2)
    assert (found.research_sessions, found.investigations) == (1, 2)


async def test_only_waiting_and_running_jobs_are_pending(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, "Wire")
    await report_event(session_factory, source, "Harbour flood", evidence_count=4)
    async with session_factory() as session:
        chunks = list(await session.scalars(select(DocumentChunk.id)))
        for status in IngestionJobStatus:
            # A run has at most one job.
            run = IngestionRun(source_id=source)
            session.add(run)
            await session.flush()
            session.add(
                IngestionJob(source_id=source, run_id=run.id, status=status, available_at=NOW)
            )
        for model, statuses in (
            (EmbeddingJob, EmbeddingJobStatus),
            (EntityExtractionJob, EntityExtractionJobStatus),
            (EventExtractionJob, EventExtractionJobStatus),
            (ClaimExtractionJob, ClaimExtractionJobStatus),
        ):
            # One job per chunk: pending, running, completed and failed.
            for chunk_id, status in zip(chunks, statuses, strict=True):
                session.add(model(chunk_id=chunk_id, provider="test", model="m", status=status))
        await session.commit()

    found = await overview(session_factory)

    assert (
        found.pending_ingestion,
        found.pending_embeddings,
        found.pending_entities,
        found.pending_events,
        found.pending_claims,
    ) == (2, 2, 2, 2, 2)
    assert found.pending_processing == 0
