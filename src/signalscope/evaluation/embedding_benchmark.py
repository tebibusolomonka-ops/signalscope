import hashlib
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import datetime
from typing import Any, Protocol

from signalscope.embeddings.provider import EmbeddingInputRole, EmbeddingProvider, embed
from signalscope.evaluation.corpus import chunk_dataset
from signalscope.evaluation.dataset import RetrievalDataset
from signalscope.evaluation.evaluation_report import EvaluationReport, evaluation_report
from signalscope.evaluation.metrics import evaluate_query, summarize
from signalscope.evaluation.retrieval import DEFAULT_KS

Timer = Callable[[], float]


class BenchmarkEmbeddingProvider(EmbeddingProvider, Protocol):
    async def load(self) -> None: ...


async def benchmark_embedding(
    provider: BenchmarkEmbeddingProvider,
    dataset: RetrievalDataset,
    dataset_fingerprint: str,
    *,
    timestamp: datetime,
    limit: int | None = None,
    environment: dict[str, Any] | None = None,
    timer: Timer = time.perf_counter,
) -> EvaluationReport:
    """Run a labelled retrieval benchmark with an explicitly supplied provider."""
    queries = dataset.queries if limit is None else dataset.queries[:limit]
    chunks = chunk_dataset(dataset)
    places = [(key, chunk) for key, items in chunks.items() for chunk in items]
    passage_texts = [chunk.text for _, chunk in places]
    started = timer()
    await provider.load()
    load_seconds = timer() - started
    started = timer()
    passage_vectors = await embed(provider, passage_texts, EmbeddingInputRole.PASSAGE)
    passage_seconds = timer() - started
    started = timer()
    query_vectors = await embed(
        provider, [query.text for query in queries], EmbeddingInputRole.QUERY
    )
    query_seconds = timer() - started
    results = []
    for query, query_vector in zip(queries, query_vectors, strict=True):
        scores: dict[str, float] = {}
        for (document_key, _), passage_vector in zip(places, passage_vectors, strict=True):
            score = _cosine(query_vector, passage_vector)
            scores[document_key] = max(scores.get(document_key, -math.inf), score)
        ranked = sorted(scores, key=lambda key: (-scores[key], key))
        results.append(evaluate_query(query.key, ranked, query.relevant_documents, DEFAULT_KS))
    metrics = asdict(summarize(results, DEFAULT_KS))
    total_seconds = load_seconds + passage_seconds + query_seconds
    encoded = len(passage_texts) + len(queries)
    counts = {
        "documents": len(dataset.documents),
        "chunks_encoded": len(passage_texts),
        "queries_encoded": len(queries),
    }
    return evaluation_report(
        task="embedding_retrieval",
        model=provider.model_name,
        provider=provider.provider_name,
        dataset_name=dataset.name,
        dataset_fingerprint=dataset_fingerprint,
        created_at=timestamp.isoformat(),
        environment=environment,
        configuration={
            "dimensions": provider.dimensions,
            "query_limit": limit,
            "counts": counts,
        },
        metrics=metrics,
        timings={
            "model_load_seconds": load_seconds,
            "passage_encoding_seconds": passage_seconds,
            "query_encoding_seconds": query_seconds,
            "wall_seconds": total_seconds,
            "texts_per_second": encoded / total_seconds if total_seconds > 0 else 0.0,
        },
    )


def fingerprint_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_size = math.sqrt(sum(value * value for value in left))
    right_size = math.sqrt(sum(value * value for value in right))
    return 0.0 if left_size == 0 or right_size == 0 else dot / (left_size * right_size)
