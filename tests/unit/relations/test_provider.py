from typing import Any

import pytest

from signalscope.core.errors import ServiceUnavailableError
from signalscope.relations.provider import (
    ExtractedRelation,
    InvalidExtractedRelationError,
    RelationExtractionProvider,
    extract_relations,
)
from signalscope.relations.registry import (
    DuplicateRelationExtractorError,
    RelationExtractorRegistry,
)

pytestmark = pytest.mark.anyio

TEXT = "Ana Silva works for Acme in Porto."


class ScriptedRelations:
    provider_name = "test"
    model_name = "scripted"

    def __init__(self, *relations: ExtractedRelation) -> None:
        self.relations = list(relations)

    async def extract(self, text: str) -> list[ExtractedRelation]:
        return self.relations


def relation(**values: Any) -> ExtractedRelation:
    fields: dict[str, Any] = {
        "subject_text": "Ana Silva",
        "relation_type": "works_for",
        "object_text": "Acme",
    }
    return ExtractedRelation(**(fields | values))


def test_scripted_provider_follows_the_protocol() -> None:
    provider: RelationExtractionProvider = ScriptedRelations()

    assert (provider.provider_name, provider.model_name) == ("test", "scripted")


async def test_valid_relations_are_tidied() -> None:
    found = await extract_relations(
        ScriptedRelations(
            relation(subject_text=" Ana Silva ", relation_type=" Works_For "),
            relation(
                subject_text="Acme",
                relation_type="located_in",
                object_text="Porto",
                subject_start=20,
                subject_end=24,
                object_start=28,
                object_end=33,
                confidence=0.7,
                metadata={"schema": "media"},
            ),
        ),
        TEXT,
    )

    assert [(item.subject_text, item.relation_type, item.object_text) for item in found] == [
        ("Ana Silva", "works_for", "Acme"),
        ("Acme", "located_in", "Porto"),
    ]
    assert (found[1].subject_start, found[1].object_end, found[1].confidence) == (20, 33, 0.7)


async def test_blank_text_is_not_sent() -> None:
    assert await extract_relations(ScriptedRelations(relation()), "  ") == []


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"subject_text": " "}, "without a subject"),
        ({"relation_type": ""}, "without a relation type"),
        ({"object_text": " "}, "without an object"),
        ({"relation_type": "x" * 51}, "longer than 50"),
        ({"confidence": 1.5}, "confidence outside 0 to 1"),
        ({"confidence": float("nan")}, "confidence outside 0 to 1"),
        ({"confidence": True}, "confidence outside 0 to 1"),
        ({"subject_start": 0}, "only one subject offset"),
        ({"object_start": 20, "object_end": 99}, "object offsets 20:99 outside"),
        ({"subject_start": 0, "subject_end": 3}, "subject that is not at offsets 0:3"),
        ({"object_start": 24, "object_end": 20}, "object offsets 24:20 outside"),
        ({"metadata": ["not", "an", "object"]}, "metadata that is not an object"),
    ],
    ids=[
        "blank subject",
        "blank type",
        "blank object",
        "long type",
        "confidence too high",
        "confidence nan",
        "confidence bool",
        "one offset",
        "offsets outside",
        "offsets mismatch",
        "offsets reversed",
        "metadata",
    ],
)
async def test_bad_relations_are_rejected(values: dict[str, Any], message: str) -> None:
    with pytest.raises(InvalidExtractedRelationError, match=message):
        await extract_relations(ScriptedRelations(relation(**values)), TEXT)


def test_registry() -> None:
    registry = RelationExtractorRegistry()
    assert registry.keys() == []
    with pytest.raises(ServiceUnavailableError, match="not configured"):
        registry.get("test", "scripted")

    provider = ScriptedRelations()
    registry.register(provider)

    assert registry.keys() == [("test", "scripted")]
    assert registry.get("test", "scripted") is provider
    with pytest.raises(DuplicateRelationExtractorError):
        registry.register(ScriptedRelations())
