import math

import pytest

from signalscope.evaluation.metrics import (
    evaluate_query,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank_at_k,
    summarize,
    unique_in_order,
)

RELEVANT = {"a", "b"}


def test_perfect_ranking() -> None:
    retrieved = ["a", "b", "x"]

    assert recall_at_k(retrieved, RELEVANT, 2) == 1.0
    assert reciprocal_rank_at_k(retrieved, RELEVANT, 2) == 1.0
    assert ndcg_at_k(retrieved, RELEVANT, 2) == pytest.approx(1.0)


def test_no_relevant_document_found() -> None:
    retrieved = ["x", "y", "z"]

    assert recall_at_k(retrieved, RELEVANT, 3) == 0.0
    assert reciprocal_rank_at_k(retrieved, RELEVANT, 3) == 0.0
    assert ndcg_at_k(retrieved, RELEVANT, 3) == 0.0


def test_nothing_retrieved() -> None:
    assert recall_at_k([], RELEVANT, 5) == 0.0
    assert reciprocal_rank_at_k([], RELEVANT, 5) == 0.0
    assert ndcg_at_k([], RELEVANT, 5) == 0.0


def test_first_relevant_at_place_two() -> None:
    retrieved = ["x", "a", "y"]

    assert reciprocal_rank_at_k(retrieved, {"a"}, 3) == 0.5
    # DCG = 1 / log2(3). The best DCG, with "a" first, is 1.
    assert ndcg_at_k(retrieved, {"a"}, 3) == pytest.approx(1 / math.log2(3))
    assert reciprocal_rank_at_k(retrieved, {"a"}, 1) == 0.0


def test_several_relevant_documents() -> None:
    retrieved = ["a", "x", "b", "c"]
    relevant = {"a", "b", "c", "d"}

    assert recall_at_k(retrieved, relevant, 3) == 0.5
    assert recall_at_k(retrieved, relevant, 4) == 0.75
    # DCG@4 = 1 + 1/log2(4) + 1/log2(5); the best has four relevant documents.
    dcg = 1 + 1 / math.log2(4) + 1 / math.log2(5)
    best = 1 + 1 / math.log2(3) + 1 / math.log2(4) + 1 / math.log2(5)
    assert ndcg_at_k(retrieved, relevant, 4) == pytest.approx(dcg / best)


def test_fewer_results_than_k() -> None:
    retrieved = ["a"]

    assert recall_at_k(retrieved, RELEVANT, 10) == 0.5
    # The best list at k=10 holds both relevant documents.
    assert ndcg_at_k(retrieved, RELEVANT, 10) == pytest.approx(1 / (1 + 1 / math.log2(3)))


def test_repeated_documents_do_not_raise_scores() -> None:
    once = ["a", "x", "y"]
    repeated = ["a", "a", "a", "x", "y"]

    for k in (1, 2, 3):
        assert recall_at_k(repeated, RELEVANT, k) == recall_at_k(once, RELEVANT, k)
        assert ndcg_at_k(repeated, RELEVANT, k) == ndcg_at_k(once, RELEVANT, k)
    assert ndcg_at_k(repeated, {"a"}, 3) == pytest.approx(1.0)
    assert unique_in_order(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_different_k() -> None:
    retrieved = ["x", "y", "a"]

    assert [recall_at_k(retrieved, {"a"}, k) for k in (1, 2, 3, 10)] == [0.0, 0.0, 1.0, 1.0]
    assert reciprocal_rank_at_k(retrieved, {"a"}, 10) == pytest.approx(1 / 3)


@pytest.mark.parametrize("k", [0, -1])
def test_k_must_be_positive(k: int) -> None:
    with pytest.raises(ValueError, match="k must be at least 1"):
        recall_at_k(["a"], {"a"}, k)
    with pytest.raises(ValueError, match="k must be at least 1"):
        ndcg_at_k(["a"], {"a"}, k)


def test_relevant_documents_are_needed() -> None:
    with pytest.raises(ValueError, match="relevant document"):
        recall_at_k(["a"], set(), 1)


def test_query_metrics_and_macro_average() -> None:
    perfect = evaluate_query("q1", ["a", "x"], {"a"}, [1, 5])
    second = evaluate_query("q2", ["x", "b"], {"b"}, [1, 5])
    missed = evaluate_query("q3", ["x", "y"], {"c"}, [1, 5])

    assert perfect.query_key == "q1"
    assert (perfect.recall, perfect.reciprocal_rank) == ({1: 1.0, 5: 1.0}, {1: 1.0, 5: 1.0})
    assert second.reciprocal_rank == {1: 0.0, 5: 0.5}

    summary = summarize([perfect, second, missed], [1, 5])

    assert summary.query_count == 3
    assert summary.recall == pytest.approx({1: 1 / 3, 5: 2 / 3})
    assert summary.mrr == pytest.approx({1: 1 / 3, 5: 0.5})
    assert summary.ndcg[5] == pytest.approx((1 + 1 / math.log2(3) + 0) / 3)


def test_summary_needs_results() -> None:
    with pytest.raises(ValueError, match="at least one query"):
        summarize([], [1])
