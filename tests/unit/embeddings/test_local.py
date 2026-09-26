"""The E5 provider, with a fake in place of the real model.

Nothing here downloads or loads model files.
"""

import asyncio
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from signalscope.core.errors import ServiceUnavailableError
from signalscope.embeddings.local import (
    LocalEmbeddingsNotInstalledError,
    MultilingualE5SmallProvider,
    load_sentence_transformer,
)
from signalscope.embeddings.provider import EmbeddingError, EmbeddingInputRole, embed

pytestmark = pytest.mark.anyio


class FakeEncoder:
    """Returns short made-up vectors and records how it was called."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions
        self.calls: list[dict[str, Any]] = []
        self.threads: list[str] = []

    def encode(self, inputs: list[str], **options: Any) -> list[list[float]]:
        self.calls.append({"inputs": inputs, **options})
        self.threads.append(threading.current_thread().name)
        return [[0.5] * self.dimensions for _ in inputs]


class FakeLoader:
    def __init__(self, encoder: FakeEncoder) -> None:
        self.encoder = encoder
        self.calls: list[tuple[str, str, Path | None]] = []

    def __call__(self, model: str, device: str, cache_dir: Path | None) -> FakeEncoder:
        self.calls.append((model, device, cache_dir))
        return self.encoder


def provider_with(
    encoder: FakeEncoder | None = None, **options: Any
) -> tuple[MultilingualE5SmallProvider, FakeLoader]:
    loader = FakeLoader(encoder or FakeEncoder())
    return MultilingualE5SmallProvider(loader=loader, **options), loader


def test_model_identity() -> None:
    provider, _ = provider_with()

    assert provider.provider_name == "sentence_transformers"
    assert provider.model_name == "intfloat/multilingual-e5-small"
    assert provider.dimensions == 384


async def test_query_prefix() -> None:
    encoder = FakeEncoder()
    provider, _ = provider_with(encoder)

    await provider.embed_texts(["offshore wind"], EmbeddingInputRole.QUERY)

    assert encoder.calls[0]["inputs"] == ["query: offshore wind"]


async def test_passage_prefix() -> None:
    encoder = FakeEncoder()
    provider, _ = provider_with(encoder)

    await provider.embed_texts(["Wind farms grew.", "Rain fell."], EmbeddingInputRole.PASSAGE)

    assert encoder.calls[0]["inputs"] == ["passage: Wind farms grew.", "passage: Rain fell."]


async def test_encode_options() -> None:
    encoder = FakeEncoder()
    provider, _ = provider_with(encoder, batch_size=8)

    vectors = await provider.embed_texts(["text"], EmbeddingInputRole.PASSAGE)

    call = encoder.calls[0]
    assert call["batch_size"] == 8
    # The library normalizes, so nothing here does it a second time.
    assert call["normalize_embeddings"] is True
    assert call["show_progress_bar"] is False
    assert vectors == [[0.5] * 384]


def test_defaults() -> None:
    provider, _ = provider_with()

    assert (provider.device, provider.batch_size, provider.cache_dir) == ("cpu", 32, None)


@pytest.mark.parametrize("batch_size", [0, -1])
def test_bad_batch_size(batch_size: int) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        provider_with(batch_size=batch_size)


async def test_model_is_loaded_on_first_use_with_the_device(tmp_path: Path) -> None:
    provider, loader = provider_with(device="cuda:1", cache_dir=tmp_path)

    assert loader.calls == []
    await provider.embed_texts(["text"], EmbeddingInputRole.QUERY)

    assert loader.calls == [("intfloat/multilingual-e5-small", "cuda:1", tmp_path)]


async def test_model_is_loaded_once() -> None:
    provider, loader = provider_with()

    await asyncio.gather(
        *(provider.embed_texts(["text"], EmbeddingInputRole.QUERY) for _ in range(5))
    )
    await provider.embed_texts(["more"], EmbeddingInputRole.PASSAGE)

    assert len(loader.calls) == 1


async def test_encoding_runs_off_the_event_loop_thread() -> None:
    encoder = FakeEncoder()
    provider, _ = provider_with(encoder)

    await provider.embed_texts(["text"], EmbeddingInputRole.QUERY)

    assert encoder.threads != [threading.current_thread().name]


async def test_wrong_vector_size_is_caught() -> None:
    provider, _ = provider_with(FakeEncoder(dimensions=12))

    with pytest.raises(EmbeddingError, match="12 dimensions instead of 384"):
        await embed(provider, ["text"], EmbeddingInputRole.PASSAGE)


def test_missing_library_gives_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # None in sys.modules makes the import fail, as if the extra were not installed.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(LocalEmbeddingsNotInstalledError, match="local-embeddings") as error:
        load_sentence_transformer("intfloat/multilingual-e5-small", "cpu", None)

    assert isinstance(error.value, ServiceUnavailableError)


async def test_missing_library_surfaces_on_first_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    provider = MultilingualE5SmallProvider()

    with pytest.raises(LocalEmbeddingsNotInstalledError):
        await provider.embed_texts(["text"], EmbeddingInputRole.QUERY)
