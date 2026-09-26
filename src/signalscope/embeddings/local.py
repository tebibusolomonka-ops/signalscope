"""Local embeddings with the sentence-transformers library.

The library, and PyTorch with it, is an optional extra. It is only imported
when the model is first used, so SignalScope runs without it.
"""

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from signalscope.embeddings.models import MULTILINGUAL_E5_SMALL
from signalscope.embeddings.provider import EmbeddingInputRole
from signalscope.embeddings.registry import EmbeddingProviderUnavailableError

DEFAULT_DEVICE = "cpu"
DEFAULT_BATCH_SIZE = 32
# E5 models were trained with these prefixes, and retrieval needs them.
E5_PREFIXES = {
    EmbeddingInputRole.QUERY: "query: ",
    EmbeddingInputRole.PASSAGE: "passage: ",
}


class LocalEmbeddingsNotInstalledError(EmbeddingProviderUnavailableError):
    default_message = (
        "Local embeddings need the local-embeddings extra. "
        'Install it with: pip install -e ".[local-embeddings]"'
    )


class SentenceEncoder(Protocol):
    """The part of SentenceTransformer that SignalScope uses."""

    def encode(
        self,
        inputs: list[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
        show_progress_bar: bool,
    ) -> Any: ...


# Loads a model from its name, a device and an optional cache folder.
ModelLoader = Callable[[str, str, Path | None], SentenceEncoder]


def load_sentence_transformer(model: str, device: str, cache_dir: Path | None) -> SentenceEncoder:
    """Load a model, downloading it into the cache on first use."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise LocalEmbeddingsNotInstalledError() from error
    encoder: SentenceEncoder = SentenceTransformer(
        model, device=device, cache_folder=None if cache_dir is None else str(cache_dir)
    )
    return encoder


class MultilingualE5SmallProvider:
    """intfloat/multilingual-e5-small, run locally with sentence-transformers.

    The model is loaded on first use, not when the provider is made. Encoding
    runs in a worker thread, because it is slow and would block the event loop.
    Vectors are normalized by the library, so cosine distance fits them.
    """

    provider_name = MULTILINGUAL_E5_SMALL.provider
    model_name = MULTILINGUAL_E5_SMALL.model
    dimensions = MULTILINGUAL_E5_SMALL.dimensions

    def __init__(
        self,
        device: str = DEFAULT_DEVICE,
        batch_size: int = DEFAULT_BATCH_SIZE,
        cache_dir: Path | None = None,
        loader: ModelLoader = load_sentence_transformer,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.device = device
        self.batch_size = batch_size
        self.cache_dir = cache_dir
        self.loader = loader
        self._encoder: SentenceEncoder | None = None
        self._load_lock = asyncio.Lock()

    async def embed_texts(
        self, texts: Sequence[str], role: EmbeddingInputRole
    ) -> list[list[float]]:
        encoder = await self._load()
        prefix = E5_PREFIXES[role]
        inputs = [prefix + text for text in texts]
        return await asyncio.to_thread(self._encode, encoder, inputs)

    def _encode(self, encoder: SentenceEncoder, inputs: list[str]) -> list[list[float]]:
        vectors = encoder.encode(
            inputs,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in vector] for vector in vectors]

    async def _load(self) -> SentenceEncoder:
        # The lock stops two first calls at the same time from loading the model twice.
        async with self._load_lock:
            if self._encoder is None:
                self._encoder = await asyncio.to_thread(
                    self.loader, self.model_name, self.device, self.cache_dir
                )
        return self._encoder
