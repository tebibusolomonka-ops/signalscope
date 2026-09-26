from typing import Any

import pytest

from fake_entities import FakeEntityExtractor
from signalscope.core.errors import ServiceUnavailableError
from signalscope.entities.provider import (
    EntityExtractionProvider,
    EntityExtractorUnavailableError,
    ExtractedEntityMention,
    InvalidEntityMentionError,
    extract_mentions,
)
from signalscope.entities.registry import DuplicateEntityExtractorError, EntityExtractorRegistry

pytestmark = pytest.mark.anyio

TEXT = "Merkel met Macron in Berlin."


def mention(**values: Any) -> ExtractedEntityMention:
    fields: dict[str, Any] = {
        "text": "Macron",
        "entity_type": "person",
        "start_char": 11,
        "end_char": 17,
        "confidence": 0.5,
    }
    return ExtractedEntityMention(**(fields | values))


def test_fake_extractor_follows_the_protocol() -> None:
    extractor: EntityExtractionProvider = FakeEntityExtractor()

    assert (extractor.provider_name, extractor.model_name) == ("test", "known-words")


async def test_valid_extraction() -> None:
    mentions = await extract_mentions(FakeEntityExtractor(), TEXT)

    assert [(item.text, item.entity_type, item.start_char, item.end_char) for item in mentions] == [
        ("Merkel", "person", 0, 6),
        ("Macron", "person", 11, 17),
        ("Berlin", "location", 21, 27),
    ]
    assert all(TEXT[item.start_char : item.end_char] == item.text for item in mentions)


async def test_blank_text_calls_nothing() -> None:
    extractor = FakeEntityExtractor()

    assert await extract_mentions(extractor, "   ") == []
    assert extractor.calls == []


async def test_no_confidence_is_allowed() -> None:
    extractor = FakeEntityExtractor()
    extractor.answer = [mention(confidence=None, metadata={"label": "PER"})]

    [found] = await extract_mentions(extractor, TEXT)

    assert (found.confidence, found.metadata) == (None, {"label": "PER"})


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"start_char": -1}, "offsets -1:17 outside the text"),
        ({"end_char": 99}, "offsets 11:99 outside the text"),
        ({"start_char": 17, "end_char": 17}, "outside the text"),
        ({"start_char": 12}, "not at offsets 12:17"),
        ({"text": "macron"}, "not at offsets 11:17"),
        ({"entity_type": " "}, "entity type that is empty"),
        ({"entity_type": "t" * 51}, "longer than 50"),
        ({"confidence": 1.2}, "confidence outside 0 to 1"),
        ({"confidence": -0.1}, "confidence outside 0 to 1"),
        ({"confidence": float("nan")}, "confidence outside 0 to 1"),
        ({"confidence": float("inf")}, "confidence outside 0 to 1"),
        ({"metadata": ["x"]}, "metadata that is not an object"),
        ({"text": " ", "start_char": 6, "end_char": 7}, "only whitespace"),
    ],
    ids=[
        "negative start",
        "end past text",
        "empty span",
        "wrong offsets",
        "wrong text",
        "blank type",
        "long type",
        "confidence above one",
        "confidence below zero",
        "confidence nan",
        "confidence infinity",
        "metadata not an object",
        "only whitespace",
    ],
)
async def test_invalid_mentions_are_rejected(values: dict[str, Any], message: str) -> None:
    extractor = FakeEntityExtractor()
    extractor.answer = [mention(**values)]

    with pytest.raises(InvalidEntityMentionError, match=message) as error:
        await extract_mentions(extractor, TEXT)

    assert "test/known-words" in str(error.value)


def test_registry() -> None:
    registry = EntityExtractorRegistry()
    first, second = FakeEntityExtractor(), FakeEntityExtractor(model_name="other")

    assert registry.keys() == []
    registry.register(first)
    registry.register(second)

    assert registry.get("test", "known-words") is first
    assert registry.get("test", "other") is second
    assert registry.keys() == [("test", "known-words"), ("test", "other")]


def test_registry_rejects_the_same_model_twice() -> None:
    registry = EntityExtractorRegistry()
    registry.register(FakeEntityExtractor())

    with pytest.raises(DuplicateEntityExtractorError, match="already registered"):
        registry.register(FakeEntityExtractor())


def test_missing_model() -> None:
    with pytest.raises(EntityExtractorUnavailableError, match="test/x is not configured") as error:
        EntityExtractorRegistry().get("test", "x")

    assert isinstance(error.value, ServiceUnavailableError)


async def test_entity_types_come_back_normalized() -> None:
    extractor = FakeEntityExtractor()
    extractor.answer = [
        mention(text="Merkel", entity_type="PERSON", start_char=0, end_char=6),
        mention(entity_type=" Person "),
    ]

    found = await extract_mentions(extractor, TEXT)

    assert [item.entity_type for item in found] == ["person", "person"]
    # The span itself is left as it was.
    assert [item.text for item in found] == ["Merkel", "Macron"]
