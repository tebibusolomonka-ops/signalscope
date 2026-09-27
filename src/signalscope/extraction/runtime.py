"""The structured extraction setup that settings ask for."""

from signalscope.core.settings import Settings
from signalscope.extraction.gliner2 import (
    GLINER2_MODEL,
    GLINER2_PROVIDER,
    Gliner2StructuredBackend,
)


def create_structured_backend(settings: Settings) -> Gliner2StructuredBackend | None:
    """Return the shared GLiNER2 backend, or None when it is off.

    The model itself is only loaded when it first reads a text. Model files go
    to the same cache as the embedding model.
    """
    if not settings.local_structured_enabled:
        return None
    return Gliner2StructuredBackend(
        device=settings.local_structured_device,
        cache_dir=settings.local_embedding_cache_dir,
    )


def local_structured_model(settings: Settings) -> tuple[str, str] | None:
    """The (provider, model) that event and claim jobs are queued for, or None when off."""
    if not settings.local_structured_enabled:
        return None
    return GLINER2_PROVIDER, GLINER2_MODEL
