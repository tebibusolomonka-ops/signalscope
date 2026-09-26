import pytest

from signalscope.evaluation.retrieval import check_ks, summarize_latency


def test_ks_are_sorted_without_repeats() -> None:
    assert check_ks([10, 1, 5, 1]) == (1, 5, 10)


@pytest.mark.parametrize("ks", [[], [0], [51], [1, -2]])
def test_bad_ks(ks: list[int]) -> None:
    with pytest.raises(ValueError):
        check_ks(ks)


def test_latency_summary() -> None:
    summary = summarize_latency([0.004, 0.001, 0.003, 0.002, 0.010])

    assert summary.mean_ms == pytest.approx(4.0)
    assert summary.p50_ms == pytest.approx(3.0)
    # Between the fourth (4 ms) and fifth (10 ms) values.
    assert summary.p95_ms == pytest.approx(4 + (10 - 4) * 0.8)


def test_latency_of_one_query() -> None:
    summary = summarize_latency([0.002])

    assert (summary.mean_ms, summary.p50_ms, summary.p95_ms) == pytest.approx((2.0, 2.0, 2.0))


def test_latency_needs_times() -> None:
    with pytest.raises(ValueError):
        summarize_latency([])
