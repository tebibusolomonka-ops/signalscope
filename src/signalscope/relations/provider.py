import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from signalscope.core.errors import ServiceUnavailableError, SignalScopeError

RELATION_TYPE_MAX_LENGTH = 50


class RelationExtractorUnavailableError(ServiceUnavailableError):
    default_message = "Relation extraction model is not available."


class InvalidExtractedRelationError(SignalScopeError):
    """The model answered with a relation that does not fit the text."""

    default_message = "Relation extraction returned an invalid relation."


@dataclass(frozen=True, slots=True)
class ExtractedRelation:
    """A directed relation: subject, relation type, object.

    "Ana works_for Acme" is not the same relation as "Acme works_for Ana".
    Offsets are optional, because some models only return the words. When
    given, they come in pairs and point at the words in the text.
    """

    subject_text: str
    relation_type: str
    object_text: str
    subject_start: int | None = None
    subject_end: int | None = None
    object_start: int | None = None
    object_end: int | None = None
    # How sure the model is, from 0 to 1, when it says.
    confidence: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class RelationExtractionProvider(Protocol):
    """Finds relations in a text, with one model."""

    provider_name: str
    model_name: str

    async def extract(self, text: str) -> list[ExtractedRelation]:
        """Return the relations in text. A text may have none."""
        ...


async def extract_relations(
    provider: RelationExtractionProvider, text: str
) -> list[ExtractedRelation]:
    """Extract relations with provider and check each one against the text.

    Relation types come back trimmed and in lower case, and subject and object
    trimmed.
    """
    if not text.strip():
        return []
    relations = await provider.extract(text)
    name = f"{provider.provider_name}/{provider.model_name}"
    checked = []
    for relation in relations:
        problem = relation_problem(relation, text)
        if problem is not None:
            raise InvalidExtractedRelationError(f"Relation extraction model {name} {problem}.")
        checked.append(
            replace(
                relation,
                subject_text=relation.subject_text.strip(),
                relation_type=relation.relation_type.strip().lower(),
                object_text=relation.object_text.strip(),
            )
        )
    return checked


def relation_problem(relation: ExtractedRelation, text: str) -> str | None:
    """Say what is wrong with an extracted relation, or return None when it fits the text."""
    for value, what in (
        (relation.subject_text, "a subject"),
        (relation.relation_type, "a relation type"),
        (relation.object_text, "an object"),
    ):
        if not isinstance(value, str) or not value.strip():
            return f"returned a relation without {what}"
    if len(relation.relation_type.strip()) > RELATION_TYPE_MAX_LENGTH:
        return f"returned a relation type longer than {RELATION_TYPE_MAX_LENGTH} characters"
    for words, start, end, what in (
        (relation.subject_text, relation.subject_start, relation.subject_end, "subject"),
        (relation.object_text, relation.object_start, relation.object_end, "object"),
    ):
        problem = _span_problem(words, start, end, text, what)
        if problem is not None:
            return problem
    confidence = relation.confidence
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, int | float)
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        return "returned a confidence outside 0 to 1"
    if not isinstance(relation.metadata, Mapping):
        return "returned metadata that is not an object"
    return None


def _span_problem(
    words: str, start: int | None, end: int | None, text: str, what: str
) -> str | None:
    if start is None and end is None:
        return None
    if start is None or end is None:
        return f"returned only one {what} offset"
    if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text)):
        return f"returned {what} offsets {start}:{end} outside the text"
    if text[start:end] != words:
        return f"returned a {what} that is not at offsets {start}:{end}"
    return None
