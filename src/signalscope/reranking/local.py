"""Local reranking with the CrossEncoder of the sentence-transformers library.

The library is an optional extra. It is only imported when the model is first
used, so SignalScope runs without it.
"""

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from signalscope.reranking.models import MMARCO_MINILM
from signalscope.reranking.provider import InvalidRerankerOutputError, RerankerUnavailableError

DEFAULT_DEVICE = "cpu"
DEFAULT_BATCH_SIZE = 16


class LocalRerankingNotInstalledError(RerankerUnavailableError):
    default_message = (
        "Local reranking needs the local-reranking extra. "
        'Install it with: pip install -e ".[local-reranking]"'
    )


class PairScorer(Protocol):
    """The part of CrossEncoder that SignalScope uses."""

    def predict(
        self,
        inputs: list[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
        convert_to_numpy: bool,
    ) -> Any: ...


# Loads a model from its name, a device and an optional cache folder.
ModelLoader = Callable[[str, str, Path | None], PairScorer]


def load_cross_encoder(model: str, device: str, cache_dir: Path | None) -> PairScorer:
    """Load a model, downloading it into the cache on first use."""
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as error:
        raise LocalRerankingNotInstalledError() from error
    scorer: PairScorer = CrossEncoder(
        model, device=device, cache_folder=None if cache_dir is None else str(cache_dir)
    )
    return scorer


class MultilingualMmarcoReranker:
    """cross-encoder/mmarco-mMiniLMv2-L12-H384-v1, run locally.

    The model reads the query and a passage together and scores how well they
    match. Both are passed as plain text. The model is loaded on first use, and
    scoring runs in a worker thread, because it is slow and would block the
    event loop.
    """

    provider_name = MMARCO_MINILM.provider
    model_name = MMARCO_MINILM.model

    def __init__(
        self,
        device: str = DEFAULT_DEVICE,
        batch_size: int = DEFAULT_BATCH_SIZE,
        cache_dir: Path | None = None,
        loader: ModelLoader = load_cross_encoder,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.device = device
        self.batch_size = batch_size
        self.cache_dir = cache_dir
        self.loader = loader
        self._scorer: PairScorer | None = None
        self._load_lock = asyncio.Lock()

    async def score(self, query: str, passages: Sequence[str]) -> list[float]:
        scorer = await self._load()
        pairs = [(query, passage) for passage in passages]
        return await asyncio.to_thread(self._predict, scorer, pairs)

    def _predict(self, scorer: PairScorer, pairs: list[tuple[str, str]]) -> list[float]:
        scores = scorer.predict(
            pairs, batch_size=self.batch_size, show_progress_bar=False, convert_to_numpy=True
        )
        try:
            return [float(score) for score in scores]
        except (TypeError, ValueError):
            raise InvalidRerankerOutputError(
                f"Reranker {self.model_name} did not return one number per passage."
            ) from None

    async def _load(self) -> PairScorer:
        # The lock stops two first calls at the same time from loading the model twice.
        async with self._load_lock:
            if self._scorer is None:
                self._scorer = await asyncio.to_thread(
                    self.loader, self.model_name, self.device, self.cache_dir
                )
        return self._scorer
