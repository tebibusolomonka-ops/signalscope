import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings
from signalscope.domain.search.embedding_queue import EmbeddingTarget
from signalscope.embeddings.local import MultilingualE5SmallProvider
from signalscope.embeddings.runtime import create_embedding_registry, local_embedding_target

ENABLED = Settings(
    local_embeddings_enabled=True,
    local_embedding_device="cuda",
    local_embedding_batch_size=16,
    local_embedding_cache_dir=Path("models"),
)


@pytest.fixture(autouse=True)
def no_model_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make importing sentence-transformers fail, so any attempt to load a model shows."""
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)


def test_registry_is_empty_when_disabled() -> None:
    assert create_embedding_registry(Settings()).keys() == []


def test_e5_is_registered_when_enabled() -> None:
    registry = create_embedding_registry(ENABLED)

    assert registry.keys() == [("sentence_transformers", "intfloat/multilingual-e5-small")]
    provider = registry.get("sentence_transformers", "intfloat/multilingual-e5-small")
    assert isinstance(provider, MultilingualE5SmallProvider)
    assert (provider.device, provider.batch_size, provider.cache_dir) == (
        "cuda",
        16,
        Path("models"),
    )


def test_making_the_registry_does_not_load_the_model() -> None:
    registry = create_embedding_registry(ENABLED)

    provider = registry.get("sentence_transformers", "intfloat/multilingual-e5-small")
    assert isinstance(provider, MultilingualE5SmallProvider)
    # Loading would have failed, because the library cannot be imported here.
    assert provider._encoder is None


def test_processing_target() -> None:
    assert local_embedding_target(Settings()) is None
    assert local_embedding_target(ENABLED) == EmbeddingTarget(
        "sentence_transformers", "intfloat/multilingual-e5-small"
    )


def test_app_uses_the_configured_registry() -> None:
    disabled = create_app(Settings())
    enabled = create_app(ENABLED)

    assert disabled.state.embedding_providers.keys() == []
    assert enabled.state.embedding_providers.keys() == [
        ("sentence_transformers", "intfloat/multilingual-e5-small")
    ]


def test_app_starts_without_loading_the_model() -> None:
    with TestClient(create_app(ENABLED)) as client:
        assert client.get("/health").status_code == 200
