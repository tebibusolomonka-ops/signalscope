import hashlib
import uuid
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import chunk_text
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

TEXT = "Angela Merkel met Emmanuel Macron in Berlin."


async def create_chunk_and_entity(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[DocumentChunk, Entity]:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, content=TEXT)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunk_text(TEXT))
        entity = Entity(
            canonical_name="Angela Merkel", normalized_name="angela merkel", entity_type="person"
        )
        session.add(entity)
        await session.commit()
        [chunk] = await repository.list_by_document(document.id)
    return chunk, entity


def mention(chunk: DocumentChunk, entity: Entity, **values: Any) -> EntityMention:
    fields: dict[str, Any] = {
        "entity_id": entity.id,
        "document_id": chunk.document_id,
        "chunk_id": chunk.id,
        "surface_text": "Angela Merkel",
        "entity_type": "person",
        "start_char": 0,
        "end_char": 13,
        "confidence": 0.9,
        "provider": "test",
        "model": "ner-1",
        "chunk_text_hash": hashlib.sha256(TEXT.encode()).hexdigest(),
    }
    return EntityMention(**(fields | values))


async def add(session_factory: async_sessionmaker[AsyncSession], *mentions: EntityMention) -> None:
    async with session_factory() as session:
        session.add_all(mentions)
        await session.commit()


async def stored(session_factory: async_sessionmaker[AsyncSession]) -> list[EntityMention]:
    async with session_factory() as session:
        return list(await session.scalars(select(EntityMention)))


async def test_mention_is_stored(session_factory: async_sessionmaker[AsyncSession]) -> None:
    chunk, entity = await create_chunk_and_entity(session_factory)

    await add(session_factory, mention(chunk, entity, mention_metadata={"label": "PER"}))

    [saved] = await stored(session_factory)
    assert TEXT[saved.start_char : saved.end_char] == saved.surface_text
    assert (saved.confidence, saved.provider, saved.model) == (0.9, "test", "ner-1")
    assert saved.mention_metadata == {"label": "PER"}


async def test_metadata_defaults_to_an_empty_object(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk, entity = await create_chunk_and_entity(session_factory)

    await add(session_factory, mention(chunk, entity, confidence=None))

    [saved] = await stored(session_factory)
    assert (saved.mention_metadata, saved.confidence) == ({}, None)


@pytest.mark.parametrize(
    "values",
    [
        {"start_char": -1},
        {"end_char": 0},
        {"start_char": 5, "end_char": 5},
        {"confidence": 1.5},
        {"confidence": -0.1},
        {"chunk_text_hash": "abc"},
        {"mention_metadata": ["not", "an", "object"]},
        {"entity_id": uuid.uuid4()},
        {"chunk_id": uuid.uuid4()},
    ],
    ids=[
        "negative start",
        "end not after start",
        "empty span",
        "confidence above one",
        "confidence below zero",
        "bad hash",
        "metadata not an object",
        "unknown entity",
        "unknown chunk",
    ],
)
async def test_invalid_mention_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, Any]
) -> None:
    chunk, entity = await create_chunk_and_entity(session_factory)

    async with session_factory() as session:
        session.add(mention(chunk, entity, **values))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_one_mention_per_place_and_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk, entity = await create_chunk_and_entity(session_factory)
    await add(session_factory, mention(chunk, entity))

    async with session_factory() as session:
        session.add(mention(chunk, entity))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_another_model_may_find_the_same_place(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk, entity = await create_chunk_and_entity(session_factory)

    await add(session_factory, mention(chunk, entity), mention(chunk, entity, model="ner-2"))

    assert len(await stored(session_factory)) == 2


async def test_mentions_go_away_with_their_chunk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk, entity = await create_chunk_and_entity(session_factory)
    await add(session_factory, mention(chunk, entity))

    async with session_factory() as session:
        await DocumentChunkRepository(session).replace_for_document(
            chunk.document_id, chunk_text("Different text.")
        )
        await session.commit()

    assert await stored(session_factory) == []
    async with session_factory() as session:
        # The entity stays. It may be mentioned elsewhere.
        assert await session.get(Entity, entity.id) is not None


async def test_entity_with_mentions_cannot_be_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk, entity = await create_chunk_and_entity(session_factory)
    await add(session_factory, mention(chunk, entity))

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(delete(Entity).where(Entity.id == entity.id))
