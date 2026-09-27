"""Helpers that store sources, documents and the events they report, for tests."""

import hashlib
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.sources.model import Source, SourceType


async def create_source(session_factory: async_sessionmaker[AsyncSession], name: str) -> uuid.UUID:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name=name)
        session.add(source)
        await session.commit()
        return source.id


async def report_event(
    session_factory: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    title: str,
    event_type: str = "flood",
    occurred_at: datetime | None = None,
    evidence_count: int = 1,
) -> uuid.UUID:
    """Store a new document in the source with one event, reported by evidence_count chunks."""
    texts = [f"{title}, part {index} of {uuid.uuid4()}." for index in range(evidence_count)]
    chunks = [
        TextChunk(
            position=index,
            text=text,
            start_char=0,
            end_char=len(text),
            text_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        for index, text in enumerate(texts)
    ]
    async with session_factory() as session:
        document = Document(source_id=source_id, title=title)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        saved = await repository.list_by_document(document.id)
        event = Event(event_type=event_type, title=title, occurred_at=occurred_at)
        session.add(event)
        await session.flush()
        session.add_all(
            EventEvidence(event_id=event.id, chunk_id=chunk.id, provider="test", model="m")
            for chunk in saved
        )
        await session.commit()
        return event.id
