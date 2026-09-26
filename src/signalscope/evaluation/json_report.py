"""Machine-readable retrieval evaluation reports.

The file holds the scores and timings of each mode and which models made them.
It never holds vectors or document text. Everything but the timings is the
same on every run with the same data and models.
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from signalscope.embeddings.provider import EmbeddingProvider
from signalscope.evaluation.retrieval import LatencySummary, RetrievalReport
from signalscope.reranking.provider import RerankerProvider

REPORT_FORMAT_VERSION = 1


def report_data(
    dataset: str,
    query_count: int,
    ks: Sequence[int],
    reports: Sequence[RetrievalReport],
    skipped: Mapping[str, str] | None = None,
    embedding: EmbeddingProvider | None = None,
    reranker: RerankerProvider | None = None,
) -> dict[str, Any]:
    """Build the report as plain JSON data.

    embedding and reranker are the models used, or None when no mode used them.
    """
    return {
        "format_version": REPORT_FORMAT_VERSION,
        "dataset": dataset,
        "query_count": query_count,
        "ks": list(ks),
        "models": {
            "embedding": None
            if embedding is None
            else {
                "provider": embedding.provider_name,
                "model": embedding.model_name,
                "dimensions": embedding.dimensions,
            },
            "reranker": None
            if reranker is None
            else {"provider": reranker.provider_name, "model": reranker.model_name},
        },
        "modes": {report.mode: _mode_data(report) for report in reports},
        "skipped": dict(skipped or {}),
    }


def write_json_report(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _mode_data(report: RetrievalReport) -> dict[str, Any]:
    metrics = report.metrics
    data: dict[str, Any] = {
        "metrics": {
            "recall": _by_k(metrics.recall),
            "mrr": _by_k(metrics.mrr),
            "ndcg": _by_k(metrics.ndcg),
        },
        "queries": [
            {
                "key": query.query_key,
                "recall": _by_k(query.recall),
                "reciprocal_rank": _by_k(query.reciprocal_rank),
                "ndcg": _by_k(query.ndcg),
            }
            for query in report.queries
        ],
        "latency_ms": _latency(report.latency),
    }
    if report.reranking_latency is not None:
        data["reranking_latency_ms"] = _latency(report.reranking_latency)
    return data


def _by_k(values: Mapping[int, float]) -> dict[str, float]:
    # JSON object keys are text.
    return {str(k): value for k, value in sorted(values.items())}


def _latency(latency: LatencySummary) -> dict[str, float]:
    return {"mean": latency.mean_ms, "p50": latency.p50_ms, "p95": latency.p95_ms}
