"""Experimental relation extraction with the shared local GLiNER2 model.

This provider is for evaluation only. No worker runs it and nothing stores its
relations.
"""

import logging
from collections.abc import Mapping
from typing import Any, Protocol

from signalscope.relations.provider import (
    ExtractedRelation,
    InvalidExtractedRelationError,
    relation_problem,
)

logger = logging.getLogger(__name__)

RELATION_OUTPUT = "relation_extraction"

# A first set of relation types for media texts, with descriptions that help
# the model. It is a starting point to measure, not a complete list.
RELATION_TYPES: Mapping[str, str] = {
    "works_for": "A person works for or is employed by an organization",
    "located_in": "Something is located in a place",
    "owns": "A person or organization owns something",
    "acquired": "An organization bought another organization or asset",
    "founded": "A person or organization founded an organization",
    "member_of": "A person or organization is a member of a group",
    "supports": "Someone publicly supports a person, group, policy or idea",
    "opposes": "Someone publicly opposes a person, group, policy or idea",
    "announced": "A person or organization announced something",
    "related_to": "Two things are related in some other stated way",
}


class RelationBackend(Protocol):
    provider_name: str
    model_name: str

    async def extract_relations(
        self, text: str, relation_types: Mapping[str, str]
    ) -> dict[str, Any]: ...


class Gliner2RelationProvider:
    """Finds relations of RELATION_TYPES with GLiNER2 relation extraction.

    GLiNER2 gives a (head, tail) pair per relation, where the head is the
    subject. The pair only counts when both words are in the text exactly.
    Offsets are kept only when the words appear exactly once, so they are
    never guessed. GLiNER2 gives no score for a whole relation, so confidence
    stays None. A malformed pair is skipped with a warning; a response
    without relations fails.
    """

    def __init__(
        self, backend: RelationBackend, relation_types: Mapping[str, str] = RELATION_TYPES
    ) -> None:
        self.backend = backend
        self.relation_types = dict(relation_types)
        self.provider_name = backend.provider_name
        self.model_name = backend.model_name

    async def extract(self, text: str) -> list[ExtractedRelation]:
        output = await self.backend.extract_relations(text, self.relation_types)
        found = output.get(RELATION_OUTPUT)
        if not isinstance(found, Mapping):
            raise InvalidExtractedRelationError(
                f"Relation extraction model {self.provider_name}/{self.model_name} "
                "returned no relations object."
            )
        relations = []
        for relation_type, pairs in found.items():
            if not isinstance(pairs, list):
                logger.warning("Skipped relations of type %r: not a list", relation_type)
                continue
            for index, pair in enumerate(pairs):
                relation = _relation(str(relation_type), pair, text)
                problem = (
                    "is not a usable relation"
                    if relation is None
                    else relation_problem(relation, text)
                )
                if relation is None or problem is not None:
                    logger.warning(
                        "Skipped extracted relation %s of type %r: %s",
                        index,
                        relation_type,
                        problem,
                    )
                    continue
                relations.append(relation)
        return relations


def _relation(relation_type: str, pair: Any, text: str) -> ExtractedRelation | None:
    if isinstance(pair, Mapping):
        head, tail = _words(pair.get("head")), _words(pair.get("tail"))
    elif isinstance(pair, list | tuple) and len(pair) == 2:
        head, tail = _words(pair[0]), _words(pair[1])
    else:
        return None
    if head is None or tail is None or head not in text or tail not in text:
        return None
    subject_start, subject_end = _only_place(head, text)
    object_start, object_end = _only_place(tail, text)
    return ExtractedRelation(
        subject_text=head,
        relation_type=relation_type.strip().lower(),
        object_text=tail,
        subject_start=subject_start,
        subject_end=subject_end,
        object_start=object_start,
        object_end=object_end,
    )


def _words(value: Any) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("text")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _only_place(words: str, text: str) -> tuple[int | None, int | None]:
    """The offsets of words when they appear exactly once in text, else no offsets."""
    if text.count(words) != 1:
        return None, None
    start = text.index(words)
    return start, start + len(words)
