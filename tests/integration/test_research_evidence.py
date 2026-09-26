import hashlib
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from fake_reranker import FakeReranker
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_repository import ChunkEmbeddingRepository
from signalscope.domain.sources.model import Source, SourceType
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.reranking.provider import RerankerUnavailableError
from signalscope.reranking.registry import RerankerRegistry
from signalscope.research.evidence import ResearchEvidence, ResearchEvidenceService, ResearchMode

pytestmark = pytest.mark.anyio

# Fakes under the names of the local models, which the evidence builder uses.
E5 = ("sentence_transformers", "intfloat/multilingual-e5-small")
MMARCO = ("sentence_transformers", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")


def embedder() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider(*E5)


async def add_document(
    session_factory: async_sessionmaker[AsyncSession],
    texts: list[str],
    title: str = "Report",
    starts: list[int] | None = None,
) -> list[DocumentChunk]:
    """Store one document with a chunk per text, embedded by the fake model.

    starts gives each chunk's start offset. By default chunks do not overlap.
    """
    positions = starts or [index * 1000 for index in range(len(texts))]
    chunks = [
        TextChunk(
            position=index,
            text=value,
            start_char=start,
            end_char=start + len(value),
            text_hash=hashlib.sha256(value.encode()).hexdigest(),
            metadata={"page_number": index + 1},
        )
        for index, (value, start) in enumerate(zip(texts, positions, strict=True))
    ]
    provider = embedder()
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, title=title, url=f"https://example.test/{title}")
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        saved = await repository.list_by_document(document.id)
        for chunk in saved:
            await ChunkEmbeddingRepository(session).save(
                chunk.id, *E5, chunk.text_hash, provider.vector(chunk.text)
            )
        await session.commit()
    return saved


async def build(
    session_factory: async_sessionmaker[AsyncSession],
    query: str,
    mode: ResearchMode = ResearchMode.HYBRID,
    limit: int = 8,
    source_id: uuid.UUID | None = None,
    reranker: FakeReranker | None = None,
) -> list[ResearchEvidence]:
    providers = EmbeddingProviderRegistry()
    providers.register(embedder())
    rerankers = RerankerRegistry()
    if reranker is not None:
        rerankers.register(reranker)
    async with session_factory() as session:
        return await ResearchEvidenceService(session, providers, rerankers).build(
            query, mode=mode, limit=limit, source_id=source_id
        )


async def test_hybrid_is_the_default(session_factory: async_sessionmaker[AsyncSession]) -> None:
    [flood] = await add_document(session_factory, ["Water flooded the harbour."], title="Flood")
    await add_document(session_factory, ["Energy prices rose."], title="Energy")

    evidence = await build(session_factory, "harbour water")

    first = evidence[0]
    assert (first.evidence_id, first.chunk_id, first.document_id) == (
        "E1",
        flood.id,
        flood.document_id,
    )
    assert (first.title, first.url) == ("Flood", "https://example.test/Flood")
    assert first.chunk_metadata == {"page_number": 1}
    assert first.text == "Water flooded the harbour."
    assert "harbour" in first.excerpt
    assert set(first.scores) == {"hybrid_score", "lexical_rank", "vector_similarity"}
    assert [item.evidence_id for item in evidence] == [f"E{n}" for n in range(1, len(evidence) + 1)]


async def test_lexical_mode(session_factory: async_sessionmaker[AsyncSession]) -> None:
    await add_document(session_factory, ["Water flooded the harbour."])
    await add_document(session_factory, ["Energy prices rose."])

    evidence = await build(session_factory, "harbour", mode=ResearchMode.LEXICAL)

    [only] = evidence
    assert (only.evidence_id, set(only.scores)) == ("E1", {"rank"})


async def test_semantic_mode_cuts_an_excerpt_from_the_text(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    long_text = "Water levels rose. " + "More details here. " * 40
    await add_document(session_factory, [long_text])

    [item] = await build(session_factory, "water", mode=ResearchMode.SEMANTIC)

    assert set(item.scores) == {"similarity"}
    assert item.excerpt.endswith(" ...")
    assert long_text.startswith(item.excerpt.removesuffix(" ..."))
    assert len(item.excerpt) <= 305


async def test_reranked_mode(session_factory: async_sessionmaker[AsyncSession]) -> None:
    once, three = await add_document(
        session_factory, ["Water levels.", "Water, water and more water."]
    )

    evidence = await build(
        session_factory, "water", mode=ResearchMode.RERANKED, reranker=FakeReranker(*MMARCO)
    )

    assert [item.chunk_id for item in evidence] == [three.id, once.id]
    assert evidence[0].scores["reranker_score"] == 3.0


async def test_reranked_mode_needs_a_reranker(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(RerankerUnavailableError):
        await build(session_factory, "water", mode=ResearchMode.RERANKED)


async def test_source_filter(session_factory: async_sessionmaker[AsyncSession]) -> None:
    await add_document(session_factory, ["Water here."])
    [other] = await add_document(session_factory, ["Water there."])
    async with session_factory() as session:
        document = await session.get(Document, other.document_id)
        assert document is not None
        source_id = document.source_id

    evidence = await build(session_factory, "water", source_id=source_id)

    assert [item.chunk_id for item in evidence] == [other.id]


async def test_one_document_gives_at_most_two_pieces(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_document(session_factory, [f"Water note number {n}." for n in range(5)])
    [other] = await add_document(session_factory, ["Water elsewhere."])

    evidence = await build(session_factory, "water", limit=5)

    documents = [item.document_id for item in evidence]
    assert len(evidence) == 3
    assert documents.count(other.document_id) == 1


async def test_overlapping_chunks_are_not_repeated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # The second chunk starts inside the first one, as the chunker makes them.
    first, overlapping, apart = await add_document(
        session_factory,
        ["Water rose in the harbour.", "Water rose again.", "Water fell later."],
        starts=[0, 10, 500],
    )

    evidence = await build(session_factory, "water", mode=ResearchMode.LEXICAL)

    chosen = {item.chunk_id for item in evidence}
    assert overlapping.id not in chosen or first.id not in chosen
    assert apart.id in chosen


async def test_ids_follow_the_order_and_are_stable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    for number in range(3):
        await add_document(session_factory, [f"Water report {number}."], title=f"Report {number}")

    first = await build(session_factory, "water")
    second = await build(session_factory, "water")

    assert [(item.evidence_id, item.chunk_id) for item in first] == [
        (item.evidence_id, item.chunk_id) for item in second
    ]
    assert [item.evidence_id for item in first] == ["E1", "E2", "E3"]
