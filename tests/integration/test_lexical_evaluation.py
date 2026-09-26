import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import chunk_text
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType
from signalscope.evaluation.dataset import EvaluationDocument, EvaluationQuery, RetrievalDataset
from signalscope.evaluation.retrieval import evaluate_lexical

pytestmark = pytest.mark.anyio

DOCUMENTS = (
    EvaluationDocument("wind", "Offshore wind farms doubled their output this year."),
    EvaluationDocument("rain", "Heavy rain flooded the harbour district."),
    EvaluationDocument("grid", "The power grid needs new storage for wind and solar."),
)


def dataset(*queries: EvaluationQuery) -> RetrievalDataset:
    return RetrievalDataset("smoke", DOCUMENTS, queries)


def query(key: str, text: str, *relevant: str) -> EvaluationQuery:
    return EvaluationQuery(key, text, frozenset(relevant))


async def test_perfect_retrieval(session_factory: async_sessionmaker[AsyncSession]) -> None:
    report = await evaluate_lexical(
        session_factory,
        dataset(query("q1", "heavy rain", "rain"), query("q2", "offshore farms", "wind")),
        ks=[1, 5],
    )

    assert (report.mode, report.dataset, report.ks) == ("lexical", "smoke", (1, 5))
    assert report.metrics.query_count == 2
    assert report.metrics.recall == {1: 1.0, 5: 1.0}
    assert report.metrics.mrr == {1: 1.0, 5: 1.0}
    assert report.metrics.ndcg == pytest.approx({1: 1.0, 5: 1.0})


async def test_partial_retrieval(session_factory: async_sessionmaker[AsyncSession]) -> None:
    # Only "wind" and "grid" mention wind, and "rain" is relevant too but has no match.
    report = await evaluate_lexical(
        session_factory, dataset(query("q1", "wind", "wind", "grid", "rain")), ks=[5]
    )

    [result] = report.queries
    assert result.query_key == "q1"
    assert result.recall[5] == pytest.approx(2 / 3)
    assert result.reciprocal_rank[5] == 1.0


async def test_no_matches(session_factory: async_sessionmaker[AsyncSession]) -> None:
    report = await evaluate_lexical(
        session_factory, dataset(query("q1", "volcano eruption", "rain")), ks=[10]
    )

    assert report.metrics.recall == {10: 0.0}
    assert report.metrics.mrr == {10: 0.0}
    assert report.metrics.ndcg == {10: 0.0}


async def test_only_the_evaluation_documents_are_searched(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Normal data that matches the query better must not show up.
    text = "Heavy rain, heavy rain, heavy rain in every district."
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, content=text)
        session.add(document)
        await session.flush()
        await DocumentChunkRepository(session).replace_for_document(document.id, chunk_text(text))
        await session.commit()

    report = await evaluate_lexical(session_factory, dataset(query("q1", "heavy rain", "rain")))

    assert report.metrics.mrr[1] == 1.0
    async with session_factory() as session:
        # The temporary rows were rolled back, and the normal document is still there.
        assert await session.scalar(select(func.count()).select_from(Document)) == 1


async def test_timing_is_reported(session_factory: async_sessionmaker[AsyncSession]) -> None:
    ticks = iter([0.0, 0.002, 1.0, 1.004])

    report = await evaluate_lexical(
        session_factory,
        dataset(query("q1", "heavy rain", "rain"), query("q2", "wind", "wind")),
        timer=lambda: next(ticks),
    )

    assert report.latency.mean_ms == pytest.approx(3.0)
    assert report.latency.p50_ms == pytest.approx(3.0)
    assert report.latency.p95_ms > report.latency.p50_ms


async def test_default_ks(session_factory: async_sessionmaker[AsyncSession]) -> None:
    report = await evaluate_lexical(session_factory, dataset(query("q1", "heavy rain", "rain")))

    assert report.ks == (1, 5, 10)
    assert set(report.metrics.recall) == {1, 5, 10}
