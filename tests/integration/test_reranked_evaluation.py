"""Reranked evaluation with a fake embedding model and fake rerankers.

The documents are the ones from the hybrid evaluation tests, where hybrid
search puts "both" first for the query "harbour water".
"""

from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from fake_reranker import FakeReranker
from signalscope.evaluation.dataset import EvaluationDocument, EvaluationQuery, RetrievalDataset
from signalscope.evaluation.retrieval import evaluate_hybrid, evaluate_reranked

pytestmark = pytest.mark.anyio

DOCUMENTS = (
    EvaluationDocument("short", "Harbour water. Energy energy energy energy."),
    EvaluationDocument("both", "Harbour report and some energy notes. Water levels."),
    EvaluationDocument("water", "Water only."),
    EvaluationDocument("mixed", "Water and climate energy energy."),
)


class PreferringReranker(FakeReranker):
    """Scores passages that start with one of the favourite texts 1, all others 0."""

    def __init__(self, *favourites: str) -> None:
        super().__init__()
        self.favourites = favourites

    async def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.calls.append((query, list(passages)))
        return [1.0 if passage.startswith(self.favourites) else 0.0 for passage in passages]


def dataset(
    *relevant: str, documents: tuple[EvaluationDocument, ...] = DOCUMENTS
) -> RetrievalDataset:
    query = EvaluationQuery("q1", "harbour water", frozenset(relevant))
    return RetrievalDataset("rerank", documents, (query,))


async def test_reranker_can_lift_a_relevant_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeEmbeddingProvider()

    hybrid = await evaluate_hybrid(session_factory, dataset("short"), provider, ks=[1])
    reranked = await evaluate_reranked(
        session_factory, dataset("short"), provider, PreferringReranker("Harbour water."), ks=[1]
    )

    assert hybrid.metrics.mrr == {1: 0.0}
    assert reranked.mode == "reranked"
    assert reranked.metrics.mrr == {1: 1.0}


async def test_reranker_can_push_a_relevant_document_down(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeEmbeddingProvider()

    hybrid = await evaluate_hybrid(session_factory, dataset("both"), provider, ks=[1, 5])
    reranked = await evaluate_reranked(
        session_factory, dataset("both"), provider, PreferringReranker("Water only."), ks=[1, 5]
    )

    assert hybrid.metrics.mrr == {1: 1.0, 5: 1.0}
    assert reranked.metrics.mrr[1] == 0.0
    assert reranked.metrics.recall[5] == 1.0


async def test_reranker_sees_the_query_and_the_full_chunks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    reranker = FakeReranker()

    await evaluate_reranked(session_factory, dataset("both"), FakeEmbeddingProvider(), reranker)

    [(query, passages)] = reranker.calls
    assert query == "harbour water"
    assert sorted(passages) == sorted(document.text for document in DOCUMENTS)


async def test_a_document_counts_once(session_factory: async_sessionmaker[AsyncSession]) -> None:
    long_text = "\n\n".join(
        f"Harbour part {number} with water. " + "Other details follow here. " * 20
        for number in range(5)
    )
    documents = (EvaluationDocument("long", long_text), *DOCUMENTS)

    report = await evaluate_reranked(
        session_factory,
        dataset("long", "water", documents=documents),
        FakeEmbeddingProvider(),
        PreferringReranker("Harbour part", "Water only."),
        ks=[2],
    )

    # The chunks of the long document and the water document all score 1.
    # Counted one by one, long chunks could fill the top 2. Counted once per
    # document, both relevant documents make it.
    assert report.metrics.recall == {2: 1.0}


async def test_search_and_reranking_times_are_separate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Search for the query takes 2 ms, reranking it takes 5 ms.
    ticks = iter([0.0, 0.002, 1.0, 1.005])

    report = await evaluate_reranked(
        session_factory,
        dataset("both"),
        FakeEmbeddingProvider(),
        FakeReranker(),
        timer=lambda: next(ticks),
    )

    assert report.latency.mean_ms == pytest.approx(2.0)
    assert report.reranking_latency is not None
    assert report.reranking_latency.mean_ms == pytest.approx(5.0)


async def test_other_modes_have_no_reranking_time(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    report = await evaluate_hybrid(session_factory, dataset("both"), FakeEmbeddingProvider())

    assert report.reranking_latency is None
