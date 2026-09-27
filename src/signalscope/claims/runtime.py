"""The claim extraction setup that settings ask for."""

from signalscope.claims.gliner2 import Gliner2ClaimProvider
from signalscope.claims.registry import ClaimExtractorRegistry
from signalscope.core.settings import Settings
from signalscope.extraction.gliner2 import Gliner2StructuredBackend
from signalscope.extraction.runtime import create_structured_backend


def create_claim_extractor_registry(
    settings: Settings, backend: Gliner2StructuredBackend | None = None
) -> ClaimExtractorRegistry:
    """Return the claim models to use. Empty unless local structured extraction is on.

    backend lets the event provider share one loaded model. Nothing is loaded here.
    """
    registry = ClaimExtractorRegistry()
    if backend is None:
        backend = create_structured_backend(settings)
    if backend is not None:
        registry.register(Gliner2ClaimProvider(backend))
    return registry
