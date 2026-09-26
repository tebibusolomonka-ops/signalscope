import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from signalscope.core.errors import ServiceUnavailableError, SignalScopeError
from signalscope.domain.entities.model import ENTITY_NAME_MAX_LENGTH, ENTITY_TYPE_MAX_LENGTH
from signalscope.domain.entities.names import normalize_entity_type


class EntityExtractorUnavailableError(ServiceUnavailableError):
    default_message = "Entity extraction model is not available."


class InvalidEntityMentionError(SignalScopeError):
    """The model answered with a mention that does not fit the text."""

    default_message = "Entity extraction returned an invalid mention."


@dataclass(frozen=True, slots=True)
class ExtractedEntityMention:
    # The text of the mention, exactly as it appears at start_char:end_char.
    text: str
    # A short label from the model, such as "person" or "ORG".
    entity_type: str
    start_char: int
    end_char: int
    # How sure the model is, from 0 to 1, when it says.
    confidence: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class EntityExtractionProvider(Protocol):
    """Finds entity mentions in a text with one model."""

    provider_name: str
    model_name: str

    async def extract(self, text: str) -> list[ExtractedEntityMention]:
        """Return the mentions in text, with offsets into text."""
        ...


async def extract_mentions(
    provider: EntityExtractionProvider, text: str
) -> list[ExtractedEntityMention]:
    """Extract mentions with provider and check each one against the text.

    Code should call this instead of provider.extract, so every mention is
    checked the same way before it is stored. The entity types come back
    normalized, so "PERSON" and "person" are one type.
    """
    if not text.strip():
        return []
    mentions = await provider.extract(text)
    name = f"{provider.provider_name}/{provider.model_name}"
    for mention in mentions:
        problem = _problem(mention, text)
        if problem is not None:
            raise InvalidEntityMentionError(f"Entity extraction model {name} {problem}.")
    return [
        replace(mention, entity_type=normalize_entity_type(mention.entity_type))
        for mention in mentions
    ]


def _problem(mention: ExtractedEntityMention, text: str) -> str | None:
    start, end = mention.start_char, mention.end_char
    if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text)):
        return f"returned offsets {start}:{end} outside the text"
    if text[start:end] != mention.text:
        return f"returned text that is not at offsets {start}:{end}"
    if not mention.text.strip():
        return "returned a mention that is only whitespace"
    # The text also names the entity, so it must fit an entity name.
    if len(mention.text) > ENTITY_NAME_MAX_LENGTH:
        return f"returned a mention longer than {ENTITY_NAME_MAX_LENGTH} characters"
    if not mention.entity_type.strip() or len(mention.entity_type) > ENTITY_TYPE_MAX_LENGTH:
        return f"returned an entity type that is empty or longer than {ENTITY_TYPE_MAX_LENGTH}"
    confidence = mention.confidence
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, int | float)
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        return "returned a confidence outside 0 to 1"
    if not isinstance(mention.metadata, Mapping):
        return "returned metadata that is not an object"
    return None
