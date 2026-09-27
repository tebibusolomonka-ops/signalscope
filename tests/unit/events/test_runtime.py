import sys

import pytest

from signalscope.core.settings import Settings
from signalscope.events.gliner2 import Gliner2EventProvider
from signalscope.events.runtime import create_event_extractor_registry
from signalscope.extraction.gliner2 import Gliner2StructuredBackend

GLINER2 = ("gliner2", "fastino/gliner2.5-multi-v1")


@pytest.fixture(autouse=True)
def no_model_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make importing GLiNER2 fail, so any attempt to load the model shows."""
    monkeypatch.setitem(sys.modules, "gliner2", None)


def test_registry_is_empty_when_disabled() -> None:
    assert create_event_extractor_registry(Settings()).keys() == []


def test_gliner2_is_registered_when_enabled() -> None:
    registry = create_event_extractor_registry(Settings(local_structured_enabled=True))

    assert registry.keys() == [GLINER2]
    assert isinstance(registry.get(*GLINER2), Gliner2EventProvider)


def test_a_given_backend_is_shared() -> None:
    backend = Gliner2StructuredBackend()

    provider = create_event_extractor_registry(Settings(), backend).get(*GLINER2)

    assert isinstance(provider, Gliner2EventProvider)
    assert provider.backend is backend
    assert backend._extractor is None
