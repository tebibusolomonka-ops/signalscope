import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import chunk_text
from signalscope.domain.documents.model import Document
from signalscope.domain.search.repository import SearchRepository
from signalscope.domain.sources.model import Source, SourceType
from signalscope.evaluation.corpus import chunk_dataset, evaluation_corpus
from signalscope.evaluation.dataset import EvaluationDocument, EvaluationQuery, RetrievalDataset

pytestmark = pytest.mark.anyio

LONG_TEXT = "\n\n".join(
    f"Paragraph {number} about offshore wind. " + "More details here. " * 20 for number in range(6)
)
DATASET = RetrievalDataset(
    "media-smoke",
    (
        EvaluationDocument("energy-1", LONG_TEXT, "Offshore wind", "en"),
        EvaluationDocument("weather-1", "Heavy rain flooded the harbour."),
    ),
    (EvaluationQuery("q1", "offshore wind", frozenset({"energy-1"})),),
)


async def counts(session_factory: async_sessionmaker[AsyncSession]) -> tuple[int, int, int]:
    async with session_factory() as session:
        sources = await session.scalar(select(func.count()).select_from(Source))
        documents = await session.scalar(select(func.count()).select_from(Document))
        chunks = await session.scalar(select(func.count()).select_from(DocumentChunk))
    return sources or 0, documents or 0, chunks or 0


async def add_normal_document(session_factory: async_sessionmaker[AsyncSession]) -> Document:
    text = "Normal notes about offshore wind and heavy rain."
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, content=text)
        session.add(document)
        await session.flush()
        await DocumentChunkRepository(session).replace_for_document(document.id, chunk_text(text))
        await session.commit()
    return document


def test_documents_are_chunked_with_the_normal_chunker() -> None:
    chunks = chunk_dataset(DATASET)

    assert chunks["energy-1"] == chunk_text(LONG_TEXT)
    assert len(chunks["energy-1"]) > 1
    assert [chunk.text for chunk in chunks["weather-1"]] == ["Heavy rain flooded the harbour."]


async def test_corpus_holds_the_dataset(session_factory: async_sessionmaker[AsyncSession]) -> None:
    chunks = chunk_dataset(DATASET)

    async with evaluation_corpus(session_factory, DATASET, chunks) as (session, corpus):
        # Rows are only readable inside, because the transaction is rolled back after.
        source = await session.get(Source, corpus.source_id)
        assert source is not None and source.name == "Evaluation: media-smoke"
        documents = list(
            await session.scalars(select(Document).where(Document.source_id == corpus.source_id))
        )
        by_key = {corpus.document_keys[document.id]: document for document in documents}
        wind = by_key["energy-1"]
        assert (wind.title, wind.content, wind.language, wind.external_id) == (
            "Offshore wind",
            LONG_TEXT,
            "en",
            "energy-1",
        )
        stored = await DocumentChunkRepository(session).list_by_document(wind.id)
        assert [chunk.text for chunk in stored] == [chunk.text for chunk in chunks["energy-1"]]
        assert corpus.chunk_ids[("energy-1", 0)] == stored[0].id

    assert sorted(corpus.document_keys.values()) == ["energy-1", "weather-1"]
    assert len(corpus.chunk_ids) == len(chunks["energy-1"]) + 1


async def test_lexical_search_sees_only_the_corpus(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    normal = await add_normal_document(session_factory)

    async with evaluation_corpus(session_factory, DATASET, chunk_dataset(DATASET)) as (
        session,
        corpus,
    ):
        everything = await SearchRepository(session).search("heavy rain", limit=10)
        results = await SearchRepository(session).search(
            "heavy rain", limit=10, source_id=corpus.source_id
        )

    assert normal.id in {result.document_id for result in everything}
    assert corpus.keys_of([result.document_id for result in results]) == ["weather-1"]


async def test_nothing_stays_behind(session_factory: async_sessionmaker[AsyncSession]) -> None:
    normal = await add_normal_document(session_factory)
    before = await counts(session_factory)

    async with evaluation_corpus(session_factory, DATASET, chunk_dataset(DATASET)) as (
        session,
        _,
    ):
        inside = await session.scalar(select(func.count()).select_from(Document))

    assert inside == before[1] + 2
    assert await counts(session_factory) == before
    async with session_factory() as session:
        assert await session.get(Document, normal.id) is not None


async def test_rollback_also_happens_after_an_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    before = await counts(session_factory)

    with pytest.raises(RuntimeError, match="stop"):
        async with evaluation_corpus(session_factory, DATASET, chunk_dataset(DATASET)):
            raise RuntimeError("stop")

    assert await counts(session_factory) == before
