"""The operations queries compile for PostgreSQL and always filter by organization.

A fake session compiles each statement instead of running it, so SQL shape
errors show up without a database. The database tests check the results.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from signalscope.core.errors import ServiceUnavailableError
from signalscope.domain.operations.failed_jobs import FailedJobInspectionService
from signalscope.domain.operations.overview import OrganizationOperationsService
from signalscope.domain.operations.queues import QUEUE_TABLES, OperationsQueue, ResourceType
from signalscope.domain.tenancy.scope import ContentScope

pytestmark = pytest.mark.anyio

ORGANIZATION = uuid.uuid4()


class Result:
    def one(self) -> tuple[Any, ...]:
        return (0, 0, 0, None, None)

    def all(self) -> list[Any]:
        return []


class CompilingSession:
    def __init__(self) -> None:
        self.sql: list[str] = []

    async def execute(self, statement: Any) -> Result:
        compiled = statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}
        )
        self.sql.append(str(compiled))
        return Result()

    async def scalar(self, statement: Any) -> int:
        await self.execute(statement)
        return 0

    async def get(self, model: Any, key: Any) -> Any:
        return model(id=key, name="Harbour", slug="harbour")


class Policy:
    def __init__(self, actor: object | None = object()) -> None:
        self.actor = actor

    async def scope(self, organization_id: uuid.UUID, capability: Any) -> ContentScope:
        return ContentScope.organization(organization_id)


def test_every_queue_has_a_table_and_scope_path() -> None:
    assert set(QUEUE_TABLES) == set(OperationsQueue)
    assert QUEUE_TABLES[OperationsQueue.INGESTION].resource_type is ResourceType.SOURCE
    assert QUEUE_TABLES[OperationsQueue.PROCESSING].resource_type is ResourceType.DOCUMENT
    for queue in (
        OperationsQueue.EMBEDDING,
        OperationsQueue.ENTITY_EXTRACTION,
        OperationsQueue.EVENT_EXTRACTION,
        OperationsQueue.CLAIM_EXTRACTION,
    ):
        assert QUEUE_TABLES[queue].resource_type is ResourceType.CHUNK
    for table in QUEUE_TABLES.values():
        assert {table.status(name).value for name in ("pending", "running", "failed")} == {
            "pending",
            "running",
            "failed",
        }


async def test_overview_filters_every_queue_by_source_organization() -> None:
    session = CompilingSession()
    service = OrganizationOperationsService(session, Policy())  # type: ignore[arg-type]

    result = await service.overview(ORGANIZATION)

    assert len(result.queues) == len(OperationsQueue)
    assert len(session.sql) == len(OperationsQueue)
    for sql in session.sql:
        assert "sources.organization_id = " in sql
        assert "FILTER (WHERE" in sql


async def test_operations_need_authentication() -> None:
    service = OrganizationOperationsService(CompilingSession(), Policy(None))  # type: ignore[arg-type]

    with pytest.raises(ServiceUnavailableError):
        await service.overview(ORGANIZATION)


async def test_failed_jobs_filter_each_queue_before_paging() -> None:
    session = CompilingSession()
    service = FailedJobInspectionService(session, Policy())  # type: ignore[arg-type]

    await service.list_page(ORGANIZATION, None, 10, 20)
    await service.list_page(ORGANIZATION, OperationsQueue.PROCESSING, 10, 0)

    combined, total, single, _ = session.sql
    assert combined.count("UNION ALL") == len(OperationsQueue) - 1
    assert combined.count("sources.organization_id = ") == len(OperationsQueue)
    assert "ORDER BY" in combined and "LIMIT" in combined and "OFFSET" in combined
    assert "count(*)" in total
    assert "UNION ALL" not in single
    assert "document_processing_jobs" in single
