"""The embedding setup that settings ask for."""

from signalscope.core.settings import Settings
from signalscope.domain.search.embedding_queue import EmbeddingTarget
from signalscope.embeddings.local import MultilingualE5SmallProvider
from signalscope.embeddings.models import MULTILINGUAL_E5_SMALL
from signalscope.embeddings.registry import EmbeddingProviderRegistry


def create_embedding_registry(settings: Settings) -> EmbeddingProviderRegistry:
    """Return the providers to use. Empty unless local embeddings are enabled.

    The model itself is only loaded when it first embeds something.
    """
    registry = EmbeddingProviderRegistry()
    if settings.local_embeddings_enabled:
        registry.register(
            MultilingualE5SmallProvider(
                device=settings.local_embedding_device,
                batch_size=settings.local_embedding_batch_size,
                cache_dir=settings.local_embedding_cache_dir,
            )
        )
    return registry


def local_embedding_target(settings: Settings) -> EmbeddingTarget | None:
    """The model that new chunks are queued for, or None when embeddings are off."""
    if not settings.local_embeddings_enabled:
        return None
    return EmbeddingTarget(MULTILINGUAL_E5_SMALL.provider, MULTILINGUAL_E5_SMALL.model)
