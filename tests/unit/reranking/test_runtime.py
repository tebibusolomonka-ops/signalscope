import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings
from signalscope.reranking.local import MultilingualMmarcoReranker
from signalscope.reranking.runtime import create_reranker_registry

ENABLED = Settings(
    local_reranking_enabled=True,
    local_reranking_device="cuda",
    local_reranking_batch_size=8,
    local_embedding_cache_dir=Path("models"),
)
MODEL = ("sentence_transformers", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")


@pytest.fixture(autouse=True)
def no_model_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make importing sentence-transformers fail, so any attempt to load a model shows."""
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)


def test_registry_is_empty_when_disabled() -> None:
    assert create_reranker_registry(Settings()).keys() == []


def test_mmarco_is_registered_when_enabled() -> None:
    registry = create_reranker_registry(ENABLED)

    assert registry.keys() == [MODEL]
    reranker = registry.get(*MODEL)
    assert isinstance(reranker, MultilingualMmarcoReranker)
    assert (reranker.device, reranker.batch_size, reranker.cache_dir) == (
        "cuda",
        8,
        Path("models"),
    )


def test_making_the_registry_does_not_load_the_model() -> None:
    reranker = create_reranker_registry(ENABLED).get(*MODEL)

    assert isinstance(reranker, MultilingualMmarcoReranker)
    # Loading would have failed, because the library cannot be imported here.
    assert reranker._scorer is None


def test_reranking_is_independent_of_embeddings() -> None:
    settings = Settings(local_embeddings_enabled=True)

    assert create_reranker_registry(settings).keys() == []


def test_app_keeps_the_configured_registry() -> None:
    assert create_app(Settings()).state.rerankers.keys() == []
    assert create_app(ENABLED).state.rerankers.keys() == [MODEL]


@pytest.mark.parametrize("settings", [Settings(), ENABLED], ids=["disabled", "enabled"])
def test_app_starts_without_loading_the_model(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
