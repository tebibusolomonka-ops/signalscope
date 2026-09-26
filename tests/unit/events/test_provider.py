from datetime import UTC, datetime
from typing import Any

import pytest

from fake_events import FakeEventExtractor
from signalscope.core.errors import ServiceUnavailableError
from signalscope.events.provider import (
    EventExtractionProvider,
    EventExtractorUnavailableError,
    ExtractedEvent,
    InvalidExtractedEventError,
    extract_events,
)
from signalscope.events.registry import DuplicateEventExtractorError, EventExtractorRegistry

pytestmark = pytest.mark.anyio

TEXT = "Heavy rain fell. The river flooded the town. Schools stayed open."


def event(**values: Any) -> ExtractedEvent:
    fields: dict[str, Any] = {"event_type": "flood", "title": "Town flooded"}
    return ExtractedEvent(**(fields | values))


def test_fake_extractor_follows_the_protocol() -> None:
    extractor: EventExtractionProvider = FakeEventExtractor()

    assert (extractor.provider_name, extractor.model_name) == ("test", "flood-words")


async def test_valid_events() -> None:
    [found] = await extract_events(FakeEventExtractor(), TEXT)

    assert (found.event_type, found.title, found.confidence) == (
        "flood",
        "The river flooded the town.",
        0.6,
    )
    assert (found.summary, found.occurred_at, found.metadata) == (None, None, {"sentence": 1})


async def test_all_optional_fields() -> None:
    extractor = FakeEventExtractor()
    when = datetime(2026, 9, 21, 6, 30, tzinfo=UTC)
    extractor.answer = [
        event(
            event_type="  Flood ",
            title="  Town flooded  ",
            summary="The river rose overnight.",
            occurred_at=when,
            confidence=1,
        )
    ]

    [found] = await extract_events(extractor, TEXT)

    assert (found.event_type, found.title) == ("flood", "Town flooded")
    assert (found.summary, found.occurred_at, found.confidence) == (
        "The river rose overnight.",
        when,
        1,
    )


async def test_text_without_events() -> None:
    assert await extract_events(FakeEventExtractor(), "Schools stayed open.") == []


async def test_blank_text_calls_nothing() -> None:
    extractor = FakeEventExtractor()

    assert await extract_events(extractor, "  ") == []
    assert extractor.calls == []


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"event_type": " "}, "without a type"),
        ({"event_type": "t" * 51}, "type longer than 50"),
        ({"title": ""}, "without a title"),
        ({"title": "x" * 501}, "title longer than 500"),
        ({"summary": 5}, "summary that is not text"),
        ({"occurred_at": datetime(2026, 9, 21)}, "without a time zone"),
        ({"occurred_at": "2026-09-21"}, "without a time zone"),
        ({"confidence": 1.5}, "confidence outside 0 to 1"),
        ({"confidence": float("nan")}, "confidence outside 0 to 1"),
        ({"metadata": ["x"]}, "metadata that is not an object"),
    ],
    ids=[
        "blank type",
        "long type",
        "blank title",
        "long title",
        "summary not text",
        "naive time",
        "time as text",
        "confidence above one",
        "confidence nan",
        "metadata list",
    ],
)
async def test_invalid_events_are_rejected(values: dict[str, Any], message: str) -> None:
    extractor = FakeEventExtractor()
    extractor.answer = [event(**values)]

    with pytest.raises(InvalidExtractedEventError, match=message) as error:
        await extract_events(extractor, TEXT)

    assert "test/flood-words" in str(error.value)


def test_registry() -> None:
    registry = EventExtractorRegistry()
    first, second = FakeEventExtractor(), FakeEventExtractor(model_name="other")

    assert registry.keys() == []
    registry.register(first)
    registry.register(second)

    assert registry.get("test", "flood-words") is first
    assert registry.keys() == [("test", "flood-words"), ("test", "other")]
    with pytest.raises(DuplicateEventExtractorError, match="already registered"):
        registry.register(FakeEventExtractor())


def test_missing_model() -> None:
    with pytest.raises(EventExtractorUnavailableError, match="test/x is not configured") as error:
        EventExtractorRegistry().get("test", "x")

    assert isinstance(error.value, ServiceUnavailableError)
