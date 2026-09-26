"""Standard retrieval metrics with binary relevance.

A retrieved list is a ranked list of document keys, best first. A key that
comes back more than once only counts at its best place, so repeating a
relevant document cannot raise a score.
"""

import math
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass


def unique_in_order(keys: Iterable[str]) -> list[str]:
    """Drop repeated keys, keeping each at its first, best place."""
    return list(dict.fromkeys(keys))


def recall_at_k(retrieved: Sequence[str], relevant: Collection[str], k: int) -> float:
    """The share of the relevant documents found in the top k."""
    top = _top(retrieved, relevant, k)
    return len(set(top) & set(relevant)) / len(set(relevant))


def reciprocal_rank_at_k(retrieved: Sequence[str], relevant: Collection[str], k: int) -> float:
    """1 / place of the first relevant document in the top k, or 0 when there is none."""
    for place, key in enumerate(_top(retrieved, relevant, k), start=1):
        if key in relevant:
            return 1 / place
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Collection[str], k: int) -> float:
    """Normalized discounted cumulative gain in the top k.

    Each relevant document gains 1 / log2(place + 1). The sum is divided by the
    best possible sum, where all relevant documents come first.
    """
    top = _top(retrieved, relevant, k)
    gain = sum(_discount(place) for place, key in enumerate(top, start=1) if key in relevant)
    best = sum(_discount(place) for place in range(1, min(len(set(relevant)), k) + 1))
    return gain / best


@dataclass(frozen=True, slots=True)
class QueryMetrics:
    """The metrics of one query, by k."""

    query_key: str
    recall: dict[int, float]
    reciprocal_rank: dict[int, float]
    ndcg: dict[int, float]


@dataclass(frozen=True, slots=True)
class MetricsSummary:
    """Macro averages over queries: every query counts the same."""

    query_count: int
    recall: dict[int, float]
    mrr: dict[int, float]
    ndcg: dict[int, float]


def evaluate_query(
    query_key: str, retrieved: Sequence[str], relevant: Collection[str], ks: Sequence[int]
) -> QueryMetrics:
    return QueryMetrics(
        query_key=query_key,
        recall={k: recall_at_k(retrieved, relevant, k) for k in ks},
        reciprocal_rank={k: reciprocal_rank_at_k(retrieved, relevant, k) for k in ks},
        ndcg={k: ndcg_at_k(retrieved, relevant, k) for k in ks},
    )


def summarize(results: Sequence[QueryMetrics], ks: Sequence[int]) -> MetricsSummary:
    if not results:
        raise ValueError("at least one query result is needed")
    return MetricsSummary(
        query_count=len(results),
        recall={k: _mean(result.recall[k] for result in results) for k in ks},
        mrr={k: _mean(result.reciprocal_rank[k] for result in results) for k in ks},
        ndcg={k: _mean(result.ndcg[k] for result in results) for k in ks},
    )


def _top(retrieved: Sequence[str], relevant: Collection[str], k: int) -> list[str]:
    if k < 1:
        raise ValueError("k must be at least 1")
    if not relevant:
        raise ValueError("at least one relevant document is needed")
    return unique_in_order(retrieved)[:k]


def _discount(place: int) -> float:
    return 1 / math.log2(place + 1)


def _mean(values: Iterable[float]) -> float:
    numbers = list(values)
    return sum(numbers) / len(numbers)
