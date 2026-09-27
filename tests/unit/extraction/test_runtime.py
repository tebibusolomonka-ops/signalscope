import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings
from signalscope.extraction.gliner2 import Gliner2StructuredBackend
from signalscope.extraction.runtime import create_structured_backend

ENABLED = Settings(
    local_structured_enabled=True,
    local_structured_device="cuda",
    local_embedding_cache_dir=Path("models"),
)


@pytest.fixture(autouse=True)
def no_model_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make importing GLiNER2 fail, so any attempt to load the model shows."""
    monkeypatch.setitem(sys.modules, "gliner2", None)


def test_no_backend_when_disabled() -> None:
    assert create_structured_backend(Settings()) is None


def test_backend_when_enabled_does_not_load_the_model() -> None:
    backend = create_structured_backend(ENABLED)

    assert isinstance(backend, Gliner2StructuredBackend)
    assert (backend.model_name, backend.device, backend.cache_dir) == (
        "fastino/gliner2.5-multi-v1",
        "cuda",
        Path("models"),
    )
    # Loading would have failed, because the library cannot be imported here.
    assert backend._extractor is None


@pytest.mark.parametrize("settings", [Settings(), ENABLED], ids=["disabled", "enabled"])
def test_app_starts_without_the_model(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
