"""The experimental GLiNER2 relation provider, with a fake backend in place of the model.

Nothing here downloads or loads model files.
"""

from collections.abc import Mapping
from typing import Any

import pytest

from signalscope.relations.gliner2 import RELATION_TYPES, Gliner2RelationProvider
from signalscope.relations.provider import InvalidExtractedRelationError, extract_relations

pytestmark = pytest.mark.anyio

TEXT = "Ana Silva works for Acme. Acme is located in Porto. Acme bought Beta."


class FakeBackend:
    provider_name = "gliner2"
    model_name = "fastino/gliner2.5-multi-v1"

    def __init__(self, output: Any) -> None:
        self.output = output
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def extract_relations(self, text: str, relation_types: Mapping[str, str]) -> Any:
        self.calls.append((text, dict(relation_types)))
        return self.output


def provider(**relations: Any) -> Gliner2RelationProvider:
    return Gliner2RelationProvider(FakeBackend({"relation_extraction": relations}))


def test_identity_and_schema() -> None:
    found = provider()

    assert (found.provider_name, found.model_name) == ("gliner2", "fastino/gliner2.5-multi-v1")
    assert list(RELATION_TYPES) == [
        "works_for",
        "located_in",
        "owns",
        "acquired",
        "founded",
        "member_of",
        "supports",
        "opposes",
        "announced",
        "related_to",
    ]
    assert all(description.strip() for description in RELATION_TYPES.values())


async def test_one_relation_with_offsets() -> None:
    backend = FakeBackend({"relation_extraction": {"works_for": [("Ana Silva", "Acme")]}})

    [relation] = await extract_relations(Gliner2RelationProvider(backend), TEXT)

    assert (relation.subject_text, relation.relation_type, relation.object_text) == (
        "Ana Silva",
        "works_for",
        "Acme",
    )
    # Ana Silva appears once, so its place is certain. Acme appears three times.
    assert (relation.subject_start, relation.subject_end) == (0, 9)
    assert (relation.object_start, relation.object_end) == (None, None)
    assert relation.confidence is None
    assert backend.calls == [(TEXT, dict(RELATION_TYPES))]


async def test_several_relations_and_type_normalization() -> None:
    relations = await provider(
        located_in=[["Acme", "Porto"]],
        **{" Acquired ": [{"head": {"text": "Acme"}, "tail": {"text": "Beta"}}]},
    ).extract(TEXT)

    assert [(item.subject_text, item.relation_type, item.object_text) for item in relations] == [
        ("Acme", "located_in", "Porto"),
        ("Acme", "acquired", "Beta"),
    ]
    assert (relations[1].object_start, relations[1].object_end) == (64, 68)


async def test_words_are_trimmed_and_must_be_in_the_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    relations = await provider(
        works_for=[(" Ana Silva ", "Acme"), ("Ana", "Globex"), ("ana silva", "Acme")]
    ).extract(TEXT)

    assert [(item.subject_text, item.object_text) for item in relations] == [("Ana Silva", "Acme")]
    assert caplog.text.count("Skipped extracted relation") == 2


async def test_malformed_items_are_skipped(caplog: pytest.LogCaptureFixture) -> None:
    relations = await provider(
        works_for=[
            "Ana Silva",
            ("Ana Silva",),
            ("Ana Silva", "Acme", "Porto"),
            ("", "Acme"),
            {"head": "Ana Silva"},
            ("Ana Silva", "Acme"),
        ],
        owns="not a list",
    ).extract(TEXT)

    assert len(relations) == 1
    assert caplog.text.count("Skipped extracted relation") == 5
    assert "Skipped relations of type 'owns'" in caplog.text


@pytest.mark.parametrize("output", [{}, {"relation_extraction": []}, {"relations": {}}])
async def test_response_without_relations_fails(output: Any) -> None:
    with pytest.raises(InvalidExtractedRelationError, match="no relations object"):
        await Gliner2RelationProvider(FakeBackend(output)).extract(TEXT)


async def test_no_relations() -> None:
    assert await provider(works_for=[]).extract(TEXT) == []
