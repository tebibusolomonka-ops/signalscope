import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import chunk_text
from signalscope.domain.documents.model import Document
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

TEXT = "Heavy rain flooded the harbour district on Monday."


async def create_chunk_and_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[DocumentChunk, Event]:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, content=TEXT)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunk_text(TEXT))
        event = Event(event_type="flood", title="Harbour district flooded")
        session.add(event)
        await session.commit()
        [chunk] = await repository.list_by_document(document.id)
    return chunk, event


def evidence(chunk: DocumentChunk, event: Event, **values: Any) -> EventEvidence:
    fields: dict[str, Any] = {
        "event_id": event.id,
        "chunk_id": chunk.id,
        "confidence": 0.8,
        "provider": "test",
        "model": "events-1",
    }
    return EventEvidence(**(fields | values))


async def add(session_factory: async_sessionmaker[AsyncSession], *rows: Any) -> None:
    async with session_factory() as session:
        session.add_all(rows)
        await session.commit()


async def stored_evidence(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[EventEvidence]:
    async with session_factory() as session:
        return list(await session.scalars(select(EventEvidence)))


async def test_event_with_optional_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    occurred = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
    await add(
        session_factory,
        Event(
            event_type="flood", title="Flood", summary="Streets under water.", occurred_at=occurred
        ),
        Event(event_type="election", title="Vote"),
    )

    async with session_factory() as session:
        events = {event.title: event for event in await session.scalars(select(Event))}
    assert (events["Flood"].summary, events["Flood"].occurred_at) == (
        "Streets under water.",
        occurred,
    )
    assert (events["Vote"].summary, events["Vote"].occurred_at) == (None, None)


@pytest.mark.parametrize(
    "values", [{"event_type": " "}, {"title": ""}], ids=["blank type", "blank title"]
)
async def test_blank_event_values_are_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, str]
) -> None:
    fields = {"event_type": "flood", "title": "Flood"} | values

    async with session_factory() as session:
        session.add(Event(**fields))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_evidence_is_stored(session_factory: async_sessionmaker[AsyncSession]) -> None:
    chunk, event = await create_chunk_and_event(session_factory)

    await add(session_factory, evidence(chunk, event, evidence_metadata={"sentence": 0}))

    [saved] = await stored_evidence(session_factory)
    assert (saved.event_id, saved.chunk_id, saved.confidence) == (event.id, chunk.id, 0.8)
    assert saved.evidence_metadata == {"sentence": 0}


@pytest.mark.parametrize(
    "values",
    [
        {"confidence": 1.1},
        {"confidence": -0.5},
        {"evidence_metadata": [1, 2]},
        {"event_id": uuid.uuid4()},
        {"chunk_id": uuid.uuid4()},
    ],
    ids=["confidence above one", "confidence below zero", "metadata list", "no event", "no chunk"],
)
async def test_invalid_evidence_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, Any]
) -> None:
    chunk, event = await create_chunk_and_event(session_factory)

    async with session_factory() as session:
        session.add(evidence(chunk, event, **values))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_one_evidence_row_per_event_chunk_and_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk, event = await create_chunk_and_event(session_factory)
    await add(session_factory, evidence(chunk, event), evidence(chunk, event, model="events-2"))

    async with session_factory() as session:
        session.add(evidence(chunk, event))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_deleting_the_chunk_keeps_the_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk, event = await create_chunk_and_event(session_factory)
    await add(session_factory, evidence(chunk, event, confidence=None))

    async with session_factory() as session:
        await session.execute(delete(DocumentChunk).where(DocumentChunk.id == chunk.id))
        await session.commit()

    assert await stored_evidence(session_factory) == []
    async with session_factory() as session:
        assert await session.get(Event, event.id) is not None


async def test_deleting_the_event_removes_its_evidence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk, event = await create_chunk_and_event(session_factory)
    await add(session_factory, evidence(chunk, event))

    async with session_factory() as session:
        await session.execute(delete(Event).where(Event.id == event.id))
        await session.commit()

    assert await stored_evidence(session_factory) == []


async def test_foreign_keys(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        keys = await connection.run_sync(
            lambda sync: inspect(sync).get_foreign_keys("event_evidence")
        )

    by_column = {key["constrained_columns"][0]: key for key in keys}
    assert by_column["event_id"]["referred_table"] == "events"
    assert by_column["chunk_id"]["referred_table"] == "document_chunks"
    assert {key["options"]["ondelete"] for key in keys} == {"CASCADE"}
