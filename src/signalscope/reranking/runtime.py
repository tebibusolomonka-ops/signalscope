"""The reranking setup that settings ask for."""

from signalscope.core.settings import Settings
from signalscope.reranking.local import MultilingualMmarcoReranker
from signalscope.reranking.registry import RerankerRegistry


def create_reranker_registry(settings: Settings) -> RerankerRegistry:
    """Return the rerankers to use. Empty unless local reranking is enabled.

    The model itself is only loaded when it first scores something. Model files
    go to the same cache as the embedding model.
    """
    registry = RerankerRegistry()
    if settings.local_reranking_enabled:
        registry.register(
            MultilingualMmarcoReranker(
                device=settings.local_reranking_device,
                batch_size=settings.local_reranking_batch_size,
                cache_dir=settings.local_embedding_cache_dir,
            )
        )
    return registry
