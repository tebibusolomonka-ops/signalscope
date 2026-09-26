"""Runs a retrieval dataset through SignalScope search and scores the results."""

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.search.repository import (
    MAX_CANDIDATE_LIMIT,
    PUBLIC_SEARCH_LIMIT,
    SearchRepository,
)
from signalscope.evaluation.corpus import chunk_dataset, evaluation_corpus
from signalscope.evaluation.dataset import RetrievalDataset
from signalscope.evaluation.metrics import MetricsSummary, QueryMetrics, evaluate_query, summarize

DEFAULT_KS = (1, 5, 10)
# Search returns chunks, and several can come from one document. Asking for
# the most candidates leaves enough distinct documents for the largest k.
SEARCH_DEPTH = MAX_CANDIDATE_LIMIT

Timer = Callable[[], float]


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Query times in milliseconds."""

    mean_ms: float
    p50_ms: float
    p95_ms: float


@dataclass(frozen=True, slots=True)
class RetrievalReport:
    mode: str
    dataset: str
    ks: tuple[int, ...]
    metrics: MetricsSummary
    queries: tuple[QueryMetrics, ...]
    latency: LatencySummary


def check_ks(ks: Sequence[int]) -> tuple[int, ...]:
    """Return the k values sorted and without repeats, or raise ValueError."""
    if not ks:
        raise ValueError("at least one k is needed")
    for k in ks:
        if not 1 <= k <= PUBLIC_SEARCH_LIMIT:
            raise ValueError(f"k must be between 1 and {PUBLIC_SEARCH_LIMIT}, got {k}")
    return tuple(sorted(set(ks)))


def summarize_latency(seconds: Sequence[float]) -> LatencySummary:
    if not seconds:
        raise ValueError("at least one time is needed")
    ordered = sorted(seconds)
    return LatencySummary(
        mean_ms=sum(ordered) / len(ordered) * 1000,
        p50_ms=_percentile(ordered, 50) * 1000,
        p95_ms=_percentile(ordered, 95) * 1000,
    )


class RankedQueries:
    """Collects the ranked document keys and the time of each query."""

    def __init__(self, dataset: RetrievalDataset, ks: tuple[int, ...]) -> None:
        self.dataset = dataset
        self.ks = ks
        self.results: list[QueryMetrics] = []
        self.seconds: list[float] = []

    def add(self, query_index: int, ranked_keys: list[str], seconds: float) -> None:
        query = self.dataset.queries[query_index]
        self.results.append(
            evaluate_query(query.key, ranked_keys, query.relevant_documents, self.ks)
        )
        self.seconds.append(seconds)

    def report(self, mode: str) -> RetrievalReport:
        return RetrievalReport(
            mode=mode,
            dataset=self.dataset.name,
            ks=self.ks,
            metrics=summarize(self.results, self.ks),
            queries=tuple(self.results),
            latency=summarize_latency(self.seconds),
        )


async def evaluate_lexical(
    session_factory: async_sessionmaker[AsyncSession],
    dataset: RetrievalDataset,
    ks: Sequence[int] = DEFAULT_KS,
    timer: Timer = time.perf_counter,
) -> RetrievalReport:
    """Score PostgreSQL full text search on the dataset.

    The dataset is loaded into a temporary corpus that is rolled back at the end.
    """
    checked = check_ks(ks)
    ranked = RankedQueries(dataset, checked)
    async with evaluation_corpus(session_factory, dataset, chunk_dataset(dataset)) as (
        session,
        corpus,
    ):
        repository = SearchRepository(session)
        for index, query in enumerate(dataset.queries):
            started = timer()
            results = await repository.search(
                query.text, limit=SEARCH_DEPTH, source_id=corpus.source_id
            )
            elapsed = timer() - started
            keys = corpus.keys_of([result.document_id for result in results])
            ranked.add(index, keys, elapsed)
    return ranked.report("lexical")


def _percentile(ordered: list[float], percent: float) -> float:
    """Linear interpolation between the closest ranks, as numpy does by default."""
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
