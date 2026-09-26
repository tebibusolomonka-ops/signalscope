from collections.abc import Sequence

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.embeddings.provider import EmbeddingInputRole
from signalscope.evaluation.dataset import EvaluationDocument, EvaluationQuery, RetrievalDataset
from signalscope.evaluation.retrieval import evaluate_semantic

pytestmark = pytest.mark.anyio

# The fake model counts "climate", "energy" and "water", so the order is known.
DOCUMENTS = (
    EvaluationDocument("water", "Water water water supply."),
    EvaluationDocument("energy", "Energy energy prices."),
    EvaluationDocument("mixed", "Water and energy together."),
)
# Every chunk names water exactly once, so each one matches the query "water"
# as closely as possible.
LONG_WATER = "\n\n".join(
    f"Part {number} is about water. " + "Other details follow here. " * 20 for number in range(5)
)


def query(key: str, words: str, *relevant: str) -> EvaluationQuery:
    return EvaluationQuery(key, words, frozenset(relevant))


async def test_known_ranking(session_factory: async_sessionmaker[AsyncSession]) -> None:
    provider = FakeEmbeddingProvider()
    dataset = RetrievalDataset(
        "smoke",
        DOCUMENTS,
        (query("q1", "water", "water"), query("q2", "energy", "mixed")),
    )

    report = await evaluate_semantic(session_factory, dataset, provider, ks=[1, 3])

    assert report.mode == "semantic"
    first, second = report.queries
    assert (first.reciprocal_rank[1], first.recall[1]) == (1.0, 1.0)
    # "energy" ranks the energy document first and the mixed one second.
    assert second.reciprocal_rank == {1: 0.0, 3: 0.5}
    assert report.metrics.mrr == {1: 0.5, 3: 0.75}


async def test_passages_and_queries_use_their_roles(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeEmbeddingProvider()
    dataset = RetrievalDataset("smoke", DOCUMENTS, (query("q1", "water", "water"),))

    await evaluate_semantic(session_factory, dataset, provider)

    assert provider.roles == [EmbeddingInputRole.PASSAGE, EmbeddingInputRole.QUERY]
    assert provider.calls[1] == ["water"]


async def test_a_document_counts_once_at_its_best_chunk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dataset = RetrievalDataset(
        "smoke",
        (EvaluationDocument("long", LONG_WATER), *DOCUMENTS),
        (query("q1", "water", "long", "mixed"),),
    )

    report = await evaluate_semantic(session_factory, dataset, FakeEmbeddingProvider(), ks=[2, 3])

    # The chunks of the long document take the top places. Counted one by one,
    # they would fill the top 3 and push the mixed document out.
    [result] = report.queries
    assert result.recall == {2: 0.5, 3: 1.0}


class CheckingProvider(FakeEmbeddingProvider):
    """Records whether any database transaction is open while the model runs."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__()
        self.session_factory = session_factory
        self.open_transactions: list[int] = []

    async def embed_texts(
        self, texts: Sequence[str], role: EmbeddingInputRole
    ) -> list[list[float]]:
        async with self.session_factory() as session:
            count = await session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                    "AND state LIKE 'idle in transaction%'"
                )
            )
        self.open_transactions.append(int(count or 0))
        return await super().embed_texts(texts, role)


async def test_model_runs_before_the_transaction_opens(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = CheckingProvider(session_factory)
    dataset = RetrievalDataset("smoke", DOCUMENTS, (query("q1", "water", "water"),))

    await evaluate_semantic(session_factory, dataset, provider)

    assert provider.open_transactions == [0, 0]


async def test_each_run_uses_its_own_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dataset = RetrievalDataset("smoke", DOCUMENTS, (query("q1", "energy", "mixed"),))
    energy_only = FakeEmbeddingProvider(model_name="energy-2", words=["energy"])

    words = await evaluate_semantic(session_factory, dataset, FakeEmbeddingProvider(), ks=[1])
    energy = await evaluate_semantic(session_factory, dataset, energy_only, ks=[1])

    # The three-word model puts the energy document first. The one-word model
    # sees "energy" once in the mixed document, just like in the query.
    assert words.metrics.mrr == {1: 0.0}
    assert energy.metrics.mrr == {1: 1.0}


async def test_nothing_stays_behind(session_factory: async_sessionmaker[AsyncSession]) -> None:
    dataset = RetrievalDataset("smoke", DOCUMENTS, (query("q1", "water", "water"),))

    await evaluate_semantic(session_factory, dataset, FakeEmbeddingProvider())

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ChunkEmbedding)) == 0
