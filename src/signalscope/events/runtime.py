"""The event extraction setup that settings ask for."""

from signalscope.core.settings import Settings
from signalscope.events.gliner2 import Gliner2EventProvider
from signalscope.events.registry import EventExtractorRegistry
from signalscope.extraction.gliner2 import Gliner2StructuredBackend
from signalscope.extraction.runtime import create_structured_backend


def create_event_extractor_registry(
    settings: Settings, backend: Gliner2StructuredBackend | None = None
) -> EventExtractorRegistry:
    """Return the event models to use. Empty unless local structured extraction is on.

    backend lets the claim provider share one loaded model. Nothing is loaded here.
    """
    registry = EventExtractorRegistry()
    if backend is None:
        backend = create_structured_backend(settings)
    if backend is not None:
        registry.register(Gliner2EventProvider(backend))
    return registry
