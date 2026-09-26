import pytest

from fake_reranker import FakeReranker
from signalscope.core.errors import ServiceUnavailableError
from signalscope.reranking.provider import (
    InvalidRerankerOutputError,
    RerankerProvider,
    RerankerUnavailableError,
    rerank_scores,
)

pytestmark = pytest.mark.anyio


def test_fake_reranker_follows_the_protocol() -> None:
    reranker: RerankerProvider = FakeReranker()

    assert (reranker.provider_name, reranker.model_name) == ("test", "word-count")


async def test_scores_every_passage_in_one_call() -> None:
    reranker = FakeReranker()

    scores = await rerank_scores(
        reranker, "wind power", ["Wind power grew.", "Rain fell.", "Wind, wind and power."]
    )

    assert scores == [2.0, 0.0, 3.0]
    assert reranker.calls == [
        ("wind power", ["Wind power grew.", "Rain fell.", "Wind, wind and power."])
    ]


async def test_no_passages_calls_nothing() -> None:
    reranker = FakeReranker()

    assert await rerank_scores(reranker, "wind", []) == []
    assert reranker.calls == []


async def test_whole_numbers_become_floats() -> None:
    reranker = FakeReranker()
    reranker.answer = [1, 2]  # type: ignore[list-item]

    scores = await rerank_scores(reranker, "wind", ["a", "b"])

    assert scores == [1.0, 2.0]
    assert all(isinstance(score, float) for score in scores)


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ([1.0], "returned 1 scores for 2 passages"),
        ([1.0, 2.0, 3.0], "returned 3 scores for 2 passages"),
        ([1.0, float("nan")], "not a number"),
        ([float("inf"), 1.0], "not a number"),
        ([1.0, float("-inf")], "not a number"),
        ([1.0, "2"], "not a number"),
        ([True, 1.0], "not a number"),
    ],
    ids=["too few", "too many", "nan", "infinity", "minus infinity", "text", "boolean"],
)
async def test_bad_scores_are_rejected(answer: list[float], message: str) -> None:
    reranker = FakeReranker()
    reranker.answer = answer

    with pytest.raises(InvalidRerankerOutputError, match=message) as error:
        await rerank_scores(reranker, "wind", ["a", "b"])

    assert "test/word-count" in str(error.value)


def test_errors_mean_the_service_is_unavailable() -> None:
    assert issubclass(RerankerUnavailableError, ServiceUnavailableError)
    assert issubclass(InvalidRerankerOutputError, ServiceUnavailableError)
    assert str(RerankerUnavailableError()) == "Reranker is not available."
