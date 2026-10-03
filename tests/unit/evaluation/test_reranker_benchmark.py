from datetime import UTC, datetime

import pytest

from signalscope.evaluation.dataset import EvaluationDocument, EvaluationQuery, RetrievalDataset
from signalscope.evaluation.reranker_benchmark import benchmark_reranker


class FakeReranker:
    provider_name = "fake"
    model_name = "fake-reranker"

    async def load(self) -> None:
        pass

    async def score(self, query: str, passages: list[str]) -> list[float]:
        return [1.0 if "target" in passage else 0.0 for passage in passages]


@pytest.mark.anyio
async def test_reranker_report_has_baseline_and_reranked_metrics() -> None:
    dataset = RetrievalDataset(
        "reranker-smoke",
        (EvaluationDocument("other", "query words"), EvaluationDocument("target", "target")),
        (EvaluationQuery("q1", "query words", frozenset({"target"})),),
    )

    report = await benchmark_reranker(
        FakeReranker(),  # type: ignore[arg-type]
        dataset,
        "a" * 64,
        timestamp=datetime(2026, 10, 3, tzinfo=UTC),
    )

    assert report.metrics["baseline"]["mrr"][1] == 0.0
    assert report.metrics["reranked"]["mrr"][1] == 1.0
    assert report.metrics["pairs_scored"] == 2
