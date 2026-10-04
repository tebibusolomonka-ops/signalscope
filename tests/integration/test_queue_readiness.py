from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.diagnostics.queue_readiness import QueueReadinessService
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from tenancy_helpers import add_document, add_source

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def queue(report: object, name: str) -> object:
    return next(item for item in report.queues if item.queue == name)  # type: ignore[attr-defined]


async def test_empty_queues_are_queryable_and_zero(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        report = await QueueReadinessService(session, clock=lambda: NOW).observe()

    assert report.all_queryable is True
    embedding = queue(report, "embedding")
    assert (embedding.waiting, embedding.running, embedding.expired_leases) == (0, 0, 0)
    assert embedding.oldest_waiting_age_seconds is None


async def test_counts_waiting_running_and_expired_leases(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await add_source(session_factory, None, "Queue source")
    _, chunk_ids = await add_document(session_factory, source_id, "Queue doc", ["text"])
    chunk_id = chunk_ids[0]
    async with session_factory() as session:
        session.add_all(
            [
                EmbeddingJob(
                    chunk_id=chunk_id,
                    provider="test",
                    model="waiting",
                    status=EmbeddingJobStatus.PENDING,
                    available_at=NOW - timedelta(seconds=60),
                ),
                EmbeddingJob(
                    chunk_id=chunk_id,
                    provider="test",
                    model="running",
                    status=EmbeddingJobStatus.RUNNING,
                    available_at=NOW - timedelta(seconds=120),
                    lease_expires_at=NOW + timedelta(seconds=300),
                ),
                EmbeddingJob(
                    chunk_id=chunk_id,
                    provider="test",
                    model="expired",
                    status=EmbeddingJobStatus.RUNNING,
                    available_at=NOW - timedelta(seconds=120),
                    lease_expires_at=NOW - timedelta(seconds=10),
                ),
            ]
        )
        await session.commit()

    async with session_factory() as session:
        report = await QueueReadinessService(session, clock=lambda: NOW).observe()

    embedding = queue(report, "embedding")
    assert embedding.query_available is True
    assert embedding.waiting == 1
    assert embedding.running == 2
    assert embedding.expired_leases == 1
    assert embedding.oldest_waiting_age_seconds == 60.0
