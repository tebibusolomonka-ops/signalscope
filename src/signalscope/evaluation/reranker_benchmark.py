import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol

from signalscope.evaluation.dataset import RetrievalDataset
from signalscope.evaluation.metrics import evaluate_query, summarize
from signalscope.evaluation.retrieval import DEFAULT_KS
from signalscope.reranking.provider import RerankerProvider, rerank_scores


class BenchmarkReranker(RerankerProvider, Protocol):
    async def load(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RerankerBenchmarkReport:
    model_id: str
    timestamp: str
    dataset: str
    dataset_fingerprint: str
    configuration: dict[str, Any]
    metrics: dict[str, Any]
    timings: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def benchmark_reranker(
    provider: BenchmarkReranker,
    dataset: RetrievalDataset,
    fingerprint: str,
    *,
    timestamp: datetime,
    limit: int | None = None,
    timer: Callable[[], float] = time.perf_counter,
) -> RerankerBenchmarkReport:
    queries = dataset.queries if limit is None else dataset.queries[:limit]
    started = timer()
    await provider.load()
    load_seconds = timer() - started
    baseline_results = []
    reranked_results = []
    scoring_seconds = 0.0
    pairs = 0
    for query in queries:
        terms = set(query.text.lower().split())
        baseline = sorted(
            dataset.documents,
            key=lambda item: (-len(terms & set(item.text.lower().split())), item.key),
        )
        started = timer()
        scores = await rerank_scores(provider, query.text, [item.text for item in baseline])
        scoring_seconds += timer() - started
        pairs += len(baseline)
        reranked = [
            baseline[index].key
            for index in sorted(range(len(baseline)), key=lambda index: -scores[index])
        ]
        baseline_results.append(
            evaluate_query(
                query.key, [item.key for item in baseline], query.relevant_documents, DEFAULT_KS
            )
        )
        reranked_results.append(
            evaluate_query(query.key, reranked, query.relevant_documents, DEFAULT_KS)
        )
    return RerankerBenchmarkReport(
        model_id=provider.model_name,
        timestamp=timestamp.isoformat(),
        dataset=dataset.name,
        dataset_fingerprint=fingerprint,
        configuration={"provider": provider.provider_name, "query_limit": limit},
        metrics={
            "baseline": asdict(summarize(baseline_results, DEFAULT_KS)),
            "reranked": asdict(summarize(reranked_results, DEFAULT_KS)),
            "pairs_scored": pairs,
        },
        timings={
            "model_load_seconds": load_seconds,
            "scoring_seconds": scoring_seconds,
            "pairs_per_second": pairs / scoring_seconds if scoring_seconds > 0 else 0.0,
        },
    )
