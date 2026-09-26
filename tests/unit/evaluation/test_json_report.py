import json
from pathlib import Path

from fake_embeddings import FakeEmbeddingProvider
from fake_reranker import FakeReranker
from signalscope.evaluation.json_report import report_data, write_json_report
from signalscope.evaluation.metrics import MetricsSummary, QueryMetrics
from signalscope.evaluation.retrieval import LatencySummary, RetrievalReport


def report(mode: str, reranking: bool = False) -> RetrievalReport:
    latency = LatencySummary(mean_ms=2.5, p50_ms=2.0, p95_ms=4.0)
    return RetrievalReport(
        mode=mode,
        dataset="media-smoke",
        ks=(1, 10),
        metrics=MetricsSummary(
            query_count=2, recall={10: 1.0, 1: 0.5}, mrr={1: 0.5, 10: 0.75}, ndcg={1: 0.5, 10: 0.8}
        ),
        queries=(
            QueryMetrics("q1", {1: 1.0, 10: 1.0}, {1: 1.0, 10: 1.0}, {1: 1.0, 10: 1.0}),
            QueryMetrics("q2", {1: 0.0, 10: 1.0}, {1: 0.0, 10: 0.5}, {1: 0.0, 10: 0.6}),
        ),
        latency=latency,
        reranking_latency=LatencySummary(mean_ms=9.0, p50_ms=8.0, p95_ms=12.0)
        if reranking
        else None,
    )


def test_structure() -> None:
    data = report_data(
        "media-smoke",
        2,
        (1, 10),
        [report("lexical"), report("reranked", reranking=True)],
        embedding=FakeEmbeddingProvider(),
        reranker=FakeReranker(),
    )

    assert data["format_version"] == 1
    assert (data["dataset"], data["query_count"], data["ks"]) == ("media-smoke", 2, [1, 10])
    assert data["models"] == {
        "embedding": {"provider": "test", "model": "words-4", "dimensions": 4},
        "reranker": {"provider": "test", "model": "word-count"},
    }
    assert list(data["modes"]) == ["lexical", "reranked"]
    lexical = data["modes"]["lexical"]
    assert lexical["metrics"] == {
        "recall": {"1": 0.5, "10": 1.0},
        "mrr": {"1": 0.5, "10": 0.75},
        "ndcg": {"1": 0.5, "10": 0.8},
    }
    assert lexical["queries"][1] == {
        "key": "q2",
        "recall": {"1": 0.0, "10": 1.0},
        "reciprocal_rank": {"1": 0.0, "10": 0.5},
        "ndcg": {"1": 0.0, "10": 0.6},
    }
    assert lexical["latency_ms"] == {"mean": 2.5, "p50": 2.0, "p95": 4.0}
    assert "reranking_latency_ms" not in lexical
    assert data["modes"]["reranked"]["reranking_latency_ms"] == {
        "mean": 9.0,
        "p50": 8.0,
        "p95": 12.0,
    }
    assert data["skipped"] == {}


def test_lexical_only_names_no_models() -> None:
    data = report_data("media-smoke", 2, (1,), [report("lexical")], {"reranked": "Not enabled."})

    assert data["models"] == {"embedding": None, "reranker": None}
    assert data["skipped"] == {"reranked": "Not enabled."}


def test_round_trip(tmp_path: Path) -> None:
    data = report_data("médias", 2, (1, 10), [report("hybrid")], embedding=FakeEmbeddingProvider())
    path = tmp_path / "report.json"

    write_json_report(path, data)

    assert json.loads(path.read_text(encoding="utf-8")) == data
    assert "médias" in path.read_text(encoding="utf-8")


def test_same_input_gives_the_same_file(tmp_path: Path) -> None:
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    for path in (first, second):
        write_json_report(path, report_data("media-smoke", 2, (1, 10), [report("lexical")]))

    assert first.read_bytes() == second.read_bytes()
