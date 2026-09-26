"""A dataset loaded into PostgreSQL for one evaluation run, then rolled back.

Search runs against real Document and DocumentChunk rows, so the dataset is
written into the database inside one transaction. The rows live in their own
Source, which every search filters on, so they never mix with normal data. At
the end the transaction is rolled back and nothing stays behind.
"""

import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk, chunk_text
from signalscope.domain.documents.model import (
    EXTERNAL_ID_MAX_LENGTH,
    LANGUAGE_MAX_LENGTH,
    Document,
)
from signalscope.domain.sources.model import SOURCE_NAME_MAX_LENGTH, Source, SourceType
from signalscope.evaluation.dataset import EvaluationDataError, RetrievalDataset

# Chunks of each dataset document, by document key.
DatasetChunks = Mapping[str, list[TextChunk]]


def chunk_dataset(dataset: RetrievalDataset) -> dict[str, list[TextChunk]]:
    """Split every document with the normal chunker, before any database work."""
    return {document.key: chunk_text(document.text) for document in dataset.documents}


@dataclass(frozen=True, slots=True)
class EvaluationCorpus:
    source_id: uuid.UUID
    # Dataset document key of each Document row.
    document_keys: dict[uuid.UUID, str]
    # The DocumentChunk ID of each (document key, chunk position).
    chunk_ids: dict[tuple[str, int], uuid.UUID]

    def keys_of(self, document_ids: list[uuid.UUID]) -> list[str]:
        """Map ranked document IDs back to dataset keys, keeping the order."""
        return [self.document_keys[document_id] for document_id in document_ids]


async def create_corpus(
    session: AsyncSession, dataset: RetrievalDataset, chunks: DatasetChunks
) -> EvaluationCorpus:
    """Write the dataset into the session's transaction. It never commits."""
    source = Source(
        type=SourceType.UPLOAD, name=f"Evaluation: {dataset.name}"[:SOURCE_NAME_MAX_LENGTH]
    )
    session.add(source)
    await session.flush()
    repository = DocumentChunkRepository(session)
    document_keys: dict[uuid.UUID, str] = {}
    chunk_ids: dict[tuple[str, int], uuid.UUID] = {}
    for item in dataset.documents:
        if len(item.key) > EXTERNAL_ID_MAX_LENGTH:
            raise EvaluationDataError(f"Document key {item.key[:40]!r}... is too long.")
        if item.language is not None and len(item.language) > LANGUAGE_MAX_LENGTH:
            raise EvaluationDataError(f"Document {item.key!r} language is too long.")
        document = Document(
            source_id=source.id,
            external_id=item.key,
            title=item.title,
            content=item.text,
            language=item.language,
        )
        session.add(document)
        await session.flush()
        await repository.replace_for_document(document.id, chunks[item.key])
        document_keys[document.id] = item.key
        for chunk in await repository.list_by_document(document.id):
            chunk_ids[(item.key, chunk.position)] = chunk.id
    return EvaluationCorpus(source.id, document_keys, chunk_ids)


@asynccontextmanager
async def evaluation_corpus(
    session_factory: async_sessionmaker[AsyncSession],
    dataset: RetrievalDataset,
    chunks: DatasetChunks,
) -> AsyncIterator[tuple[AsyncSession, EvaluationCorpus]]:
    """Yield a session holding the dataset, and roll everything back afterwards.

    Do slow work, such as running an embedding model, before entering, so the
    transaction stays short.
    """
    async with session_factory() as session:
        try:
            corpus = await create_corpus(session, dataset, chunks)
            yield session, corpus
        finally:
            await session.rollback()
