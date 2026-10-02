from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from operations_helpers import add_content, add_job
from signalscope.domain.ingestion.job_repository import IngestionJobRepository
from signalscope.domain.operations.attempt import (
    OperationAttempt,
    OperationAttemptOutcome,
    OperationAttemptQueue,
)
from signalscope.domain.operations.queues import QUEUE_TABLES, OperationsQueue
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from tenancy_helpers import make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def repository(queue: OperationsQueue, session: AsyncSession) -> object:
    if queue is OperationsQueue.INGESTION:
        return IngestionJobRepository(session)
    return DocumentProcessingJobRepository(session)


@pytest.mark.parametrize("queue", [OperationsQueue.INGESTION, OperationsQueue.PROCESSING])
async def test_claim_and_failure_record_one_safe_attempt(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    queue: OperationsQueue,
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    content = await add_content(session_factory, tenants.a.id, queue.value)
    job_id = await add_job(session_factory, queue, content, "pending")

    async with session_factory() as session:
        jobs = repository(queue, session)
        claimed = await jobs.claim_next(NOW)  # type: ignore[attr-defined]
        assert claimed is not None and claimed.lease_token is not None
        await session.commit()
        await jobs.mark_failed(  # type: ignore[attr-defined]
            job_id, claimed.lease_token, NOW + timedelta(minutes=1), "x" * 800
        )
        await session.commit()

    async with session_factory() as session:
        attempts = list(await session.scalars(select(OperationAttempt)))
    assert len(attempts) == 1
    attempt = attempts[0]
    expected_queue = OperationAttemptQueue(queue.value)
    assert (attempt.organization_id, attempt.queue_name, attempt.job_id) == (
        tenants.a.id,
        expected_queue,
        job_id,
    )
    assert (attempt.attempt_number, attempt.outcome) == (1, OperationAttemptOutcome.FAILED)
    assert attempt.started_at == NOW
    assert attempt.finished_at == NOW + timedelta(minutes=1)
    assert attempt.safe_error is not None and len(attempt.safe_error) == 1000
    assert "lease_token" not in {column.name for column in attempt.__table__.columns}


@pytest.mark.parametrize("queue", [OperationsQueue.INGESTION, OperationsQueue.PROCESSING])
async def test_recovery_closes_attempt_and_next_claim_starts_another(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    queue: OperationsQueue,
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    content = await add_content(session_factory, tenants.a.id, f"{queue.value}-recovery")
    job_id = await add_job(session_factory, queue, content, "pending")
    model = QUEUE_TABLES[queue].model

    async with session_factory() as session:
        jobs = repository(queue, session)
        assert await jobs.claim_next(NOW) is not None  # type: ignore[attr-defined]
        await session.commit()
        await session.execute(
            update(model)
            .where(model.id == job_id)
            .values(lease_expires_at=NOW - timedelta(seconds=1))
        )
        await session.commit()
        assert await jobs.recover_stale(NOW, 1)  # type: ignore[attr-defined]
        await session.commit()
        assert await jobs.claim_next(NOW) is not None  # type: ignore[attr-defined]
        await session.commit()

    async with session_factory() as session:
        attempts = list(
            await session.scalars(
                select(OperationAttempt).order_by(OperationAttempt.attempt_number)
            )
        )
    assert [(item.attempt_number, item.outcome) for item in attempts] == [
        (1, OperationAttemptOutcome.RECOVERED),
        (2, OperationAttemptOutcome.RUNNING),
    ]
    assert attempts[0].safe_error == "Worker lease expired."


async def test_legacy_job_does_not_create_unscoped_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from signalscope.domain.ingestion.model import IngestionJob, IngestionRun, IngestionStatus
    from signalscope.domain.sources.model import Source, SourceType

    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name="Legacy", url="https://example.com/feed")
        session.add(source)
        await session.flush()
        run = IngestionRun(source_id=source.id, status=IngestionStatus.PENDING)
        session.add(run)
        await session.flush()
        session.add(IngestionJob(source_id=source.id, run_id=run.id, available_at=NOW))
        await session.commit()
        assert await IngestionJobRepository(session).claim_next(NOW) is not None
        await session.commit()
        assert list(await session.scalars(select(OperationAttempt))) == []
