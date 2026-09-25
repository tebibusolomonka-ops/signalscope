import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.repository import DocumentFilters, DocumentRepository
from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.errors import IngestionError
from signalscope.domain.ingestion.executor import UNEXPECTED_ERROR_MESSAGE, IngestionExecutor
from signalscope.domain.ingestion.model import IngestionRun, IngestionStatus
from signalscope.domain.ingestion.registry import AdapterRegistry
from signalscope.domain.ingestion.service import IngestionRunService, InvalidStatusChangeError
from signalscope.domain.ingestion.writer import DocumentWriter
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


class ListAdapter:
    """Yields the given items, then raises the given error if there is one."""

    def __init__(self, items: list[IngestedItem], error: Exception | None = None) -> None:
        self.items = items
        self.error = error

    async def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
        for item in self.items:
            yield item
        if self.error is not None:
            raise self.error


def registry_for(adapter: ListAdapter, source_type: SourceType = SourceType.RSS) -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(source_type, adapter)
    return registry


async def create_source(
    session_factory: async_sessionmaker[AsyncSession], source_type: SourceType = SourceType.RSS
) -> Source:
    async with session_factory() as session:
        source = Source(type=source_type, name="Example", url="https://news.example/rss")
        session.add(source)
        await session.commit()
    return source


async def create_run(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> uuid.UUID:
    async with session_factory() as session:
        return (await IngestionRunService(session).create(source.id)).id


async def execute(
    session_factory: async_sessionmaker[AsyncSession], adapter: ListAdapter
) -> tuple[IngestionRun, Source]:
    source = await create_source(session_factory)
    run_id = await create_run(session_factory, source)
    run = await IngestionExecutor(session_factory, registry_for(adapter)).execute(run_id)
    return run, source


async def documents_of(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> list[Document]:
    async with session_factory() as session:
        return await DocumentRepository(session).list_page(
            DocumentFilters(source_id=source.id), limit=100, offset=0
        )


def counters(run: IngestionRun) -> tuple[int, int, int]:
    return run.items_seen, run.documents_created, run.duplicates_skipped


def item(number: int) -> IngestedItem:
    return IngestedItem(external_id=f"guid-{number}", title=f"Story {number}")


async def test_run_without_items_completes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, _ = await execute(session_factory, ListAdapter([]))

    assert run.status is IngestionStatus.COMPLETED
    assert counters(run) == (0, 0, 0)
    assert run.started_at is not None
    assert run.finished_at is not None
    assert run.finished_at >= run.started_at
    assert run.error_message is None


async def test_one_item_creates_one_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, source = await execute(session_factory, ListAdapter([item(1)]))

    assert run.status is IngestionStatus.COMPLETED
    assert counters(run) == (1, 1, 0)
    [document] = await documents_of(session_factory, source)
    assert (document.external_id, document.title) == ("guid-1", "Story 1")


async def test_many_items_create_many_documents(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, source = await execute(session_factory, ListAdapter([item(n) for n in range(5)]))

    assert counters(run) == (5, 5, 0)
    assert len(await documents_of(session_factory, source)) == 5


async def test_items_already_stored_are_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    async with session_factory() as session:
        await DocumentWriter(session).write(source.id, item(1))
        await session.commit()
    run_id = await create_run(session_factory, source)

    run = await IngestionExecutor(session_factory, registry_for(ListAdapter([item(1)]))).execute(
        run_id
    )

    assert run.status is IngestionStatus.COMPLETED
    assert counters(run) == (1, 0, 1)
    assert len(await documents_of(session_factory, source)) == 1


async def test_new_and_repeated_items_are_counted_apart(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # The feed repeats item 1, so the second copy is a duplicate of the first.
    run, source = await execute(session_factory, ListAdapter([item(1), item(2), item(1), item(3)]))

    assert counters(run) == (4, 3, 1)
    assert len(await documents_of(session_factory, source)) == 3


async def test_failure_keeps_earlier_documents_and_counts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = ListAdapter([item(1), item(2)], error=IngestionError("Feed stopped halfway."))

    run, source = await execute(session_factory, adapter)

    assert run.status is IngestionStatus.FAILED
    assert run.error_message == "Feed stopped halfway."
    assert run.finished_at is not None
    assert counters(run) == (2, 2, 0)
    assert len(await documents_of(session_factory, source)) == 2


async def test_unexpected_error_details_are_not_stored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = ListAdapter([], error=RuntimeError("connection string with a password"))

    run, _ = await execute(session_factory, adapter)

    assert run.status is IngestionStatus.FAILED
    assert run.error_message == UNEXPECTED_ERROR_MESSAGE


async def test_writer_failure_fails_the_run(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_write(self: DocumentWriter, source_id: uuid.UUID, item: IngestedItem) -> None:
        raise RuntimeError("database trouble")

    monkeypatch.setattr(DocumentWriter, "write", broken_write)

    run, source = await execute(session_factory, ListAdapter([item(1)]))

    assert run.status is IngestionStatus.FAILED
    assert run.error_message == UNEXPECTED_ERROR_MESSAGE
    assert counters(run) == (0, 0, 0)
    assert await documents_of(session_factory, source) == []


async def test_unsupported_source_type_fails_the_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, SourceType.UPLOAD)
    run_id = await create_run(session_factory, source)

    run = await IngestionExecutor(session_factory, registry_for(ListAdapter([]))).execute(run_id)

    assert run.status is IngestionStatus.FAILED
    assert run.error_message == "No ingestion adapter is available for upload sources."
    assert run.started_at is not None
    assert run.finished_at is not None


async def test_run_that_is_not_pending_is_not_executed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, _ = await execute(session_factory, ListAdapter([item(1)]))

    with pytest.raises(InvalidStatusChangeError):
        await IngestionExecutor(session_factory, registry_for(ListAdapter([item(2)]))).execute(
            run.id
        )

    async with session_factory() as session:
        again = await IngestionRunService(session).get(run.id)
    assert again.status is IngestionStatus.COMPLETED
    assert counters(again) == (1, 1, 0)


async def test_unknown_run_is_not_found(session_factory: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(NotFoundError, match="Ingestion run was not found."):
        await IngestionExecutor(session_factory, AdapterRegistry()).execute(uuid.uuid4())


class ClosingAdapter:
    """Yields many items and records when its stream is closed."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
        try:
            for number in range(10):
                yield item(number)
        finally:
            self.events.append("adapter closed")


async def test_adapter_is_closed_before_the_run_is_marked_failed(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    mark_failed = IngestionRunService.mark_failed

    async def broken_write(self: DocumentWriter, source_id: uuid.UUID, item: IngestedItem) -> None:
        raise RuntimeError("database trouble")

    async def recording_mark_failed(
        self: IngestionRunService, run_id: uuid.UUID, error_message: str
    ) -> IngestionRun:
        events.append("run failed")
        return await mark_failed(self, run_id, error_message)

    monkeypatch.setattr(DocumentWriter, "write", broken_write)
    monkeypatch.setattr(IngestionRunService, "mark_failed", recording_mark_failed)
    source = await create_source(session_factory)
    run_id = await create_run(session_factory, source)
    registry = AdapterRegistry()
    registry.register(SourceType.RSS, ClosingAdapter(events))

    run = await IngestionExecutor(session_factory, registry).execute(run_id)

    assert run.status is IngestionStatus.FAILED
    assert events == ["adapter closed", "run failed"]
