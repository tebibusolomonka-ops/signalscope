import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings
from signalscope.entities.local import MultilingualGlinerEntityProvider
from signalscope.entities.runtime import create_entity_extractor_registry, local_entity_model

ENABLED = Settings(
    local_entities_enabled=True,
    local_entity_device="cuda",
    local_entity_threshold=0.4,
    local_embedding_cache_dir=Path("models"),
)
MODEL = ("gliner", "urchade/gliner_multi-v2.1")


@pytest.fixture(autouse=True)
def no_model_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make importing GLiNER fail, so any attempt to load the model shows."""
    monkeypatch.setitem(sys.modules, "gliner", None)


def test_registry_is_empty_when_disabled() -> None:
    assert create_entity_extractor_registry(Settings()).keys() == []
    assert local_entity_model(Settings()) is None


def test_gliner_is_registered_when_enabled() -> None:
    registry = create_entity_extractor_registry(ENABLED)

    assert registry.keys() == [MODEL]
    provider = registry.get(*MODEL)
    assert isinstance(provider, MultilingualGlinerEntityProvider)
    assert (provider.device, provider.threshold, provider.cache_dir) == (
        "cuda",
        0.4,
        Path("models"),
    )
    spec = local_entity_model(ENABLED)
    assert spec is not None and (spec.provider, spec.model) == MODEL


def test_making_the_registry_does_not_load_the_model() -> None:
    provider = create_entity_extractor_registry(ENABLED).get(*MODEL)

    assert isinstance(provider, MultilingualGlinerEntityProvider)
    # Loading would have failed, because the library cannot be imported here.
    assert provider._predictor is None


@pytest.mark.parametrize("settings", [Settings(), ENABLED], ids=["disabled", "enabled"])
def test_app_keeps_the_registry_and_starts_without_the_model(settings: Settings) -> None:
    app = create_app(settings)

    assert app.state.entity_extractors.keys() == (
        [MODEL] if settings.local_entities_enabled else []
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
