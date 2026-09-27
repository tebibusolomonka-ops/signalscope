"""The answer model setup that settings ask for."""

from signalscope.core.settings import Settings
from signalscope.research.generation import AnswerGeneratorRegistry
from signalscope.research.local import Qwen3LocalAnswerGenerator


def create_answer_generator_registry(settings: Settings) -> AnswerGeneratorRegistry:
    """Return the answer models to use. Empty unless local answers are enabled.

    The model itself is only loaded when it first answers. Model files go to
    the same cache as the embedding model.
    """
    registry = AnswerGeneratorRegistry()
    if settings.local_answers_enabled:
        registry.register(
            Qwen3LocalAnswerGenerator(
                device=settings.local_answer_device,
                max_new_tokens=settings.local_answer_max_new_tokens,
                cache_dir=settings.local_embedding_cache_dir,
            )
        )
    return registry
