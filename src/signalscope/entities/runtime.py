"""The entity extraction setup that settings ask for."""

from signalscope.core.settings import Settings
from signalscope.entities.local import MultilingualGlinerEntityProvider
from signalscope.entities.models import GLINER_MULTI, EntityModelSpec
from signalscope.entities.registry import EntityExtractorRegistry


def create_entity_extractor_registry(settings: Settings) -> EntityExtractorRegistry:
    """Return the entity models to use. Empty unless local entities are enabled.

    The model itself is only loaded when it first reads a text. Model files go
    to the same cache as the embedding model.
    """
    registry = EntityExtractorRegistry()
    if settings.local_entities_enabled:
        registry.register(
            MultilingualGlinerEntityProvider(
                device=settings.local_entity_device,
                threshold=settings.local_entity_threshold,
                cache_dir=settings.local_embedding_cache_dir,
            )
        )
    return registry


def local_entity_model(settings: Settings) -> EntityModelSpec | None:
    """The model that entity jobs are queued for, or None when it is off."""
    return GLINER_MULTI if settings.local_entities_enabled else None
