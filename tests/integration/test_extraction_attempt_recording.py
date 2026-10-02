from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from operations_helpers import add_content, add_job
from signalscope.domain.claims.job_repository import ClaimExtractionJobRepository
from signalscope.domain.entities.job_repository import EntityExtractionJobRepository
from signalscope.domain.events.job_repository import EventExtractionJobRepository
from signalscope.domain.operations.attempt import OperationAttempt, OperationAttemptOutcome
from signalscope.domain.operations.queues import QUEUE_TABLES, OperationsQueue
from signalscope.domain.search.embedding_job_repository import EmbeddingJobRepository
from tenancy_helpers import make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 2, 15, tzinfo=UTC)
QUEUES = [
    OperationsQueue.EMBEDDING,
    OperationsQueue.ENTITY_EXTRACTION,
    OperationsQueue.EVENT_EXTRACTION,
    OperationsQueue.CLAIM_EXTRACTION,
]


def repository(queue: OperationsQueue, session: AsyncSession) -> object:
    repositories = {
        OperationsQueue.EMBEDDING: EmbeddingJobRepository,
        OperationsQueue.ENTITY_EXTRACTION: EntityExtractionJobRepository,
        OperationsQueue.EVENT_EXTRACTION: EventExtractionJobRepository,
        OperationsQueue.CLAIM_EXTRACTION: ClaimExtractionJobRepository,
    }
    return repositories[queue](session)


async def claim(repo: object, queue: OperationsQueue) -> object:
    if queue is OperationsQueue.EMBEDDING:
        jobs = await repo.claim_batch(NOW, "test", "m", 1)  # type: ignore[attr-defined]
        return jobs[0]
    return await repo.claim_next(NOW, [("test", "m")])  # type: ignore[attr-defined]


@pytest.mark.parametrize("queue", QUEUES, ids=lambda queue: queue.value)
async def test_extraction_attempt_lifecycle(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    queue: OperationsQueue,
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    content = await add_content(session_factory, tenants.a.id, queue.value)
    job_id = await add_job(session_factory, queue, content, "pending")
    model = QUEUE_TABLES[queue].model

    async with session_factory() as session:
        repo = repository(queue, session)
        first = await claim(repo, queue)
        token = first.lease_token  # type: ignore[attr-defined]
        assert token is not None
        await session.commit()
        await session.execute(
            update(model)
            .where(model.id == job_id)
            .values(lease_expires_at=NOW - timedelta(seconds=1))
        )
        await session.commit()
        assert await repo.recover_stale(NOW, 1)  # type: ignore[attr-defined]
        await session.commit()
        second = await claim(repo, queue)
        second_token = second.lease_token  # type: ignore[attr-defined]
        assert second_token is not None
        await session.commit()
        await repo.mark_completed(  # type: ignore[attr-defined]
            job_id, second_token, NOW + timedelta(minutes=1)
        )
        await session.commit()

    async with session_factory() as session:
        attempts = list(
            await session.scalars(
                select(OperationAttempt).order_by(OperationAttempt.attempt_number)
            )
        )
    assert [(item.attempt_number, item.outcome) for item in attempts] == [
        (1, OperationAttemptOutcome.RECOVERED),
        (2, OperationAttemptOutcome.SUCCEEDED),
    ]
    assert all(item.organization_id == tenants.a.id for item in attempts)
    assert all(item.resource_type == "chunk" for item in attempts)
    assert all(item.resource_id == content.chunk_id for item in attempts)
    assert all(item.safe_error in {None, "Worker lease expired."} for item in attempts)
