"""The mMARCO reranker, with a fake in place of the real model.

Nothing here downloads or loads model files.
"""

import asyncio
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from signalscope.reranking.local import (
    LocalRerankingNotInstalledError,
    MultilingualMmarcoReranker,
    load_cross_encoder,
)
from signalscope.reranking.provider import (
    InvalidRerankerOutputError,
    RerankerUnavailableError,
    rerank_scores,
)

pytestmark = pytest.mark.anyio


class FakeCrossEncoder:
    """Scores a pair by the length of its passage, and records how it was called."""

    def __init__(self, answer: Any = None) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []
        self.threads: list[str] = []

    def predict(self, inputs: list[tuple[str, str]], **options: Any) -> Any:
        self.calls.append({"inputs": inputs, **options})
        self.threads.append(threading.current_thread().name)
        if self.answer is not None:
            return self.answer
        return [float(len(passage)) for _, passage in inputs]


class FakeLoader:
    def __init__(self, scorer: FakeCrossEncoder) -> None:
        self.scorer = scorer
        self.calls: list[tuple[str, str, Path | None]] = []

    def __call__(self, model: str, device: str, cache_dir: Path | None) -> FakeCrossEncoder:
        self.calls.append((model, device, cache_dir))
        return self.scorer


def reranker_with(
    scorer: FakeCrossEncoder | None = None, **options: Any
) -> tuple[MultilingualMmarcoReranker, FakeLoader]:
    loader = FakeLoader(scorer or FakeCrossEncoder())
    return MultilingualMmarcoReranker(loader=loader, **options), loader


def test_identity() -> None:
    reranker, _ = reranker_with()

    assert reranker.provider_name == "sentence_transformers"
    assert reranker.model_name == "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


def test_defaults() -> None:
    reranker, _ = reranker_with()

    assert (reranker.device, reranker.batch_size, reranker.cache_dir) == ("cpu", 16, None)


@pytest.mark.parametrize("batch_size", [0, -3])
def test_bad_batch_size(batch_size: int) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        reranker_with(batch_size=batch_size)


async def test_query_and_passages_go_as_plain_pairs() -> None:
    scorer = FakeCrossEncoder()
    reranker, _ = reranker_with(scorer)

    await reranker.score("offshore wind", ["Wind farms grew.", "Rain fell."])

    # No E5 "query: " or "passage: " prefixes. Those belong to the embedding model.
    assert scorer.calls[0]["inputs"] == [
        ("offshore wind", "Wind farms grew."),
        ("offshore wind", "Rain fell."),
    ]


async def test_predict_options() -> None:
    scorer = FakeCrossEncoder()
    reranker, _ = reranker_with(scorer, batch_size=4)

    await reranker.score("wind", ["a"])

    call = scorer.calls[0]
    assert (call["batch_size"], call["show_progress_bar"]) == (4, False)


async def test_scores_keep_the_passage_order() -> None:
    reranker, _ = reranker_with()

    scores = await reranker.score("wind", ["four", "a", "three"])

    assert scores == [4.0, 1.0, 5.0]


async def test_model_is_loaded_on_first_use_with_the_device(tmp_path: Path) -> None:
    reranker, loader = reranker_with(device="cuda:0", cache_dir=tmp_path)

    assert loader.calls == []
    await reranker.score("wind", ["a"])

    assert loader.calls == [("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", "cuda:0", tmp_path)]


async def test_model_is_loaded_once() -> None:
    reranker, loader = reranker_with()

    await asyncio.gather(*(reranker.score("wind", ["a"]) for _ in range(5)))
    await reranker.score("rain", ["b"])

    assert len(loader.calls) == 1


async def test_scoring_runs_off_the_event_loop_thread() -> None:
    scorer = FakeCrossEncoder()
    reranker, _ = reranker_with(scorer)

    await reranker.score("wind", ["a"])

    assert scorer.threads != [threading.current_thread().name]


async def test_output_that_is_not_one_number_per_passage() -> None:
    reranker, _ = reranker_with(FakeCrossEncoder(answer=[[0.1, 0.9], [0.2, 0.8]]))

    with pytest.raises(InvalidRerankerOutputError, match="one number per passage"):
        await reranker.score("wind", ["a", "b"])


async def test_wrong_score_count_is_caught_by_the_shared_check() -> None:
    reranker, _ = reranker_with(FakeCrossEncoder(answer=[0.5]))

    with pytest.raises(InvalidRerankerOutputError, match="1 scores for 2 passages"):
        await rerank_scores(reranker, "wind", ["a", "b"])


def test_missing_library_gives_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # None in sys.modules makes the import fail, as if the extra were not installed.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(LocalRerankingNotInstalledError, match="local-reranking") as error:
        load_cross_encoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", "cpu", None)

    assert isinstance(error.value, RerankerUnavailableError)


async def test_missing_library_surfaces_on_first_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(LocalRerankingNotInstalledError):
        await MultilingualMmarcoReranker().score("wind", ["a"])
