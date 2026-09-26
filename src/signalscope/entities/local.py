"""Local entity extraction with the GLiNER library.

The library, and PyTorch with it, is an optional extra. It is only imported
when the model is first used, so SignalScope runs without it.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from signalscope.entities.models import ENTITY_LABELS, GLINER_MULTI
from signalscope.entities.provider import (
    EntityExtractorUnavailableError,
    ExtractedEntityMention,
    InvalidEntityMentionError,
)

DEFAULT_DEVICE = "cpu"
# Spans the model is less sure about are dropped. 0.5 is the library default.
DEFAULT_THRESHOLD = 0.5


class LocalEntitiesNotInstalledError(EntityExtractorUnavailableError):
    default_message = (
        "Local entity extraction needs the local-entities extra. "
        'Install it with: pip install -e ".[local-entities]"'
    )


class SpanPredictor(Protocol):
    """The part of the GLiNER model that SignalScope uses."""

    def predict_entities(
        self, text: str, labels: list[str], *, threshold: float
    ) -> list[dict[str, Any]]: ...


# Loads a model from its name, a device and an optional cache folder.
ModelLoader = Callable[[str, str, Path | None], SpanPredictor]


def load_gliner(model: str, device: str, cache_dir: Path | None) -> SpanPredictor:
    """Load a model, downloading it into the cache on first use."""
    try:
        from gliner import GLiNER
    except ImportError as error:
        raise LocalEntitiesNotInstalledError() from error
    predictor: SpanPredictor = GLiNER.from_pretrained(
        model, cache_dir=cache_dir, map_location=device
    )
    return predictor


class MultilingualGlinerEntityProvider:
    """urchade/gliner_multi-v2.1, run locally.

    GLiNER finds spans for the labels it is given, here ENTITY_LABELS, with a
    score for each. Spans scoring below threshold are left out. The model is
    loaded on first use, and runs in a worker thread, because it is slow and
    would block the event loop. Its output is checked by extract_mentions like
    any other provider's.
    """

    provider_name = GLINER_MULTI.provider
    model_name = GLINER_MULTI.model

    def __init__(
        self,
        device: str = DEFAULT_DEVICE,
        threshold: float = DEFAULT_THRESHOLD,
        cache_dir: Path | None = None,
        labels: Sequence[str] = ENTITY_LABELS,
        loader: ModelLoader = load_gliner,
    ) -> None:
        if not 0 < threshold <= 1:
            raise ValueError("threshold must be above 0 and at most 1")
        self.device = device
        self.threshold = threshold
        self.cache_dir = cache_dir
        self.labels = tuple(labels)
        self.loader = loader
        self._predictor: SpanPredictor | None = None
        self._load_lock = asyncio.Lock()

    async def extract(self, text: str) -> list[ExtractedEntityMention]:
        predictor = await self._load()
        spans = await asyncio.to_thread(
            predictor.predict_entities, text, list(self.labels), threshold=self.threshold
        )
        return [self._mention(span) for span in spans]

    def _mention(self, span: Any) -> ExtractedEntityMention:
        if not isinstance(span, Mapping):
            raise InvalidEntityMentionError(
                f"{self.model_name} returned a span that is not an object."
            )
        try:
            return ExtractedEntityMention(
                text=str(span["text"]),
                entity_type=str(span["label"]),
                start_char=span["start"],
                end_char=span["end"],
                confidence=span.get("score"),
            )
        except KeyError as error:
            raise InvalidEntityMentionError(
                f"{self.model_name} returned a span without {error.args[0]}."
            ) from None

    async def _load(self) -> SpanPredictor:
        # The lock stops two first calls at the same time from loading the model twice.
        async with self._load_lock:
            if self._predictor is None:
                self._predictor = await asyncio.to_thread(
                    self.loader, self.model_name, self.device, self.cache_dir
                )
        return self._predictor
