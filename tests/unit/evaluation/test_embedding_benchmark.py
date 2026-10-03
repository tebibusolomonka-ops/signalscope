from datetime import UTC, datetime

import pytest

from signalscope.embeddings.provider import EmbeddingInputRole
from signalscope.evaluation.dataset import (
    EvaluationDocument,
    EvaluationQuery,
    RetrievalDataset,
)
from signalscope.evaluation.embedding_benchmark import benchmark_embedding, fingerprint_bytes


class FakeProvider:
    provider_name = "fake"
    model_name = "fake-e5"
    dimensions = 2

    def __init__(self) -> None:
        self.loaded = False

    async def load(self) -> None:
        self.loaded = True

    async def embed_texts(self, texts: list[str], role: EmbeddingInputRole) -> list[list[float]]:
        assert self.loaded
        return [[1.0, 0.0] if "harbour" in text else [0.0, 1.0] for text in texts]


def dataset() -> RetrievalDataset:
    return RetrievalDataset(
        name="embedding-smoke",
        documents=(
            EvaluationDocument("harbour", "harbour shipping report"),
            EvaluationDocument("energy", "solar energy report"),
        ),
        queries=(
            EvaluationQuery("q1", "harbour news", frozenset({"harbour"})),
            EvaluationQuery("q2", "solar news", frozenset({"energy"})),
        ),
    )


@pytest.mark.anyio
async def test_fake_embedding_benchmark_report_shape() -> None:
    times = iter([0.0, 0.5, 0.5, 1.5, 1.5, 2.0])

    report = await benchmark_embedding(
        FakeProvider(),
        dataset(),
        fingerprint_bytes(b"dataset"),
        timestamp=datetime(2026, 10, 3, tzinfo=UTC),
        timer=lambda: next(times),
    )

    assert report.model == "fake-e5"
    assert report.dataset["fingerprint"] == fingerprint_bytes(b"dataset")
    assert report.configuration["counts"] == {
        "documents": 2,
        "chunks_encoded": 2,
        "queries_encoded": 2,
    }
    assert report.configuration["dimensions"] == 2
    assert report.metrics["recall"][1] == 1.0
    assert report.timings == {
        "model_load_seconds": 0.5,
        "passage_encoding_seconds": 1.0,
        "query_encoding_seconds": 0.5,
        "wall_seconds": 2.0,
        "texts_per_second": 2.0,
    }


@pytest.mark.anyio
async def test_query_limit_is_applied() -> None:
    report = await benchmark_embedding(
        FakeProvider(),
        dataset(),
        "a" * 64,
        timestamp=datetime(2026, 10, 3, tzinfo=UTC),
        limit=1,
    )

    assert report.configuration["counts"]["queries_encoded"] == 1
    assert report.metrics["query_count"] == 1
