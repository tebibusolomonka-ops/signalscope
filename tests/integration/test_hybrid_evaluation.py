"""Hybrid evaluation with a fake model that only counts climate, energy and water.

The documents are written so that full text search and the fake vectors
disagree in known ways.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from signalscope.evaluation.dataset import EvaluationDocument, EvaluationQuery, RetrievalDataset
from signalscope.evaluation.retrieval import (
    evaluate_hybrid,
    evaluate_lexical,
    evaluate_semantic,
)

pytestmark = pytest.mark.anyio


def query(key: str, words: str, *relevant: str) -> EvaluationQuery:
    return EvaluationQuery(key, words, frozenset(relevant))


async def test_both_searches_agree(session_factory: async_sessionmaker[AsyncSession]) -> None:
    dataset = RetrievalDataset(
        "agree",
        (
            EvaluationDocument("water", "Water supply."),
            EvaluationDocument("energy", "Energy prices energy."),
        ),
        (query("q1", "water", "water"),),
    )

    report = await evaluate_hybrid(session_factory, dataset, FakeEmbeddingProvider(), ks=[1])

    assert report.mode == "hybrid"
    assert report.metrics.mrr == {1: 1.0}
    assert report.latency.p95_ms >= 0


async def test_document_found_only_by_vectors(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # No document has the word "supply", so full text search finds nothing.
    dataset = RetrievalDataset(
        "semantic only",
        (
            EvaluationDocument("water", "Water flows."),
            EvaluationDocument("energy", "Energy prices energy."),
        ),
        (query("q1", "water supply", "water"),),
    )

    lexical = await evaluate_lexical(session_factory, dataset, ks=[1])
    hybrid = await evaluate_hybrid(session_factory, dataset, FakeEmbeddingProvider(), ks=[1])

    assert lexical.metrics.mrr == {1: 0.0}
    assert hybrid.metrics.mrr == {1: 1.0}


async def test_document_found_only_by_full_text(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Only the harbour document has both words, but its vector is the furthest.
    dataset = RetrievalDataset(
        "lexical only",
        (
            EvaluationDocument("harbour", "Harbour water. Energy energy energy energy."),
            EvaluationDocument("water", "Water."),
            EvaluationDocument("mixed", "Water energy."),
        ),
        (query("q1", "harbour water", "harbour"),),
    )

    semantic = await evaluate_semantic(session_factory, dataset, FakeEmbeddingProvider(), ks=[1])
    hybrid = await evaluate_hybrid(session_factory, dataset, FakeEmbeddingProvider(), ks=[1])

    assert semantic.metrics.mrr == {1: 0.0}
    assert hybrid.metrics.mrr == {1: 1.0}


async def test_fusion_ranks_a_document_both_searches_like(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Full text: "short" (words next to each other), then "both".
    # Vectors: "water", "both", "mixed", "short".
    # Neither search puts "both" first, but second place in both lists wins.
    dataset = RetrievalDataset(
        "fusion",
        (
            EvaluationDocument("short", "Harbour water. Energy energy energy energy."),
            EvaluationDocument("both", "Harbour report and some energy notes. Water levels."),
            EvaluationDocument("water", "Water only."),
            EvaluationDocument("mixed", "Water and climate energy energy."),
        ),
        (query("q1", "harbour water", "both"),),
    )
    provider = FakeEmbeddingProvider()

    lexical = await evaluate_lexical(session_factory, dataset, ks=[1])
    semantic = await evaluate_semantic(session_factory, dataset, provider, ks=[1])
    hybrid = await evaluate_hybrid(session_factory, dataset, provider, ks=[1])

    assert lexical.metrics.mrr == {1: 0.0}
    assert semantic.metrics.mrr == {1: 0.0}
    assert hybrid.metrics.mrr == {1: 1.0}


async def test_a_document_counts_once(session_factory: async_sessionmaker[AsyncSession]) -> None:
    long_text = "\n\n".join(
        f"Part {number} is about water. " + "Other details follow here. " * 20
        for number in range(5)
    )
    dataset = RetrievalDataset(
        "dedupe",
        (
            EvaluationDocument("long", long_text),
            EvaluationDocument("water", "Water flows."),
            EvaluationDocument("energy", "Energy prices."),
            EvaluationDocument("climate", "Climate goals."),
        ),
        (query("q1", "water", "long", "water"),),
    )

    report = await evaluate_hybrid(session_factory, dataset, FakeEmbeddingProvider(), ks=[2])

    # The long document has several chunks that match in both searches. They
    # count as one document, so the other water document still makes the top 2.
    assert report.metrics.recall == {2: 1.0}
