"""The GLiNER2 event provider, with a fake backend in place of the model.

Nothing here downloads or loads model files.
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from signalscope.events.gliner2 import EVENT_SCHEMA, Gliner2EventProvider, parse_event_time
from signalscope.events.provider import InvalidExtractedEventError, extract_events
from signalscope.extraction.gliner2 import StructuredSchema

pytestmark = pytest.mark.anyio

TEXT = "The river flooded the town on 4 March 2026. Voters elected a new mayor."


class FakeBackend:
    provider_name = "gliner2"
    model_name = "fastino/gliner2.5-multi-v1"

    def __init__(self, output: Any) -> None:
        self.output = output
        self.calls: list[tuple[str, StructuredSchema]] = []

    async def extract_json(self, text: str, schema: StructuredSchema) -> Any:
        self.calls.append((text, schema))
        return self.output


def provider(*records: Any) -> Gliner2EventProvider:
    return Gliner2EventProvider(FakeBackend({"event": list(records)}))


def test_identity_comes_from_the_backend() -> None:
    found = provider()

    assert (found.provider_name, found.model_name) == ("gliner2", "fastino/gliner2.5-multi-v1")


async def test_one_event() -> None:
    backend = FakeBackend(
        {
            "event": [
                {
                    "event_type": "Flood",
                    "title": "Town flooded",
                    "summary": "The river flooded the town.",
                    "occurred_at": "4 March 2026",
                }
            ]
        }
    )

    [event] = await extract_events(Gliner2EventProvider(backend), TEXT)

    assert (event.event_type, event.title, event.summary) == (
        "flood",
        "Town flooded",
        "The river flooded the town.",
    )
    assert event.occurred_at == datetime(2026, 3, 4, tzinfo=UTC)
    assert event.confidence is None
    assert event.metadata == {"occurred_at_text": "4 March 2026"}
    assert backend.calls == [(TEXT, EVENT_SCHEMA)]


async def test_several_events_with_types_normalized() -> None:
    events = await extract_events(
        provider(
            {"event_type": " FLOOD ", "title": "Town flooded"},
            {"event_type": "Election", "title": {"text": "Mayor elected", "confidence": 0.9}},
        ),
        TEXT,
    )

    assert [(event.event_type, event.title) for event in events] == [
        ("flood", "Town flooded"),
        ("election", "Mayor elected"),
    ]
    # A score for one field is not a score for the whole event.
    assert [event.confidence for event in events] == [None, None]


async def test_missing_optional_fields() -> None:
    [event] = await provider({"event_type": "flood", "title": "Town flooded"}).extract(TEXT)

    assert (event.summary, event.occurred_at, event.metadata) == (None, None, {})


async def test_unclear_date_is_kept_as_text_only() -> None:
    [event] = await provider(
        {"event_type": "flood", "title": "Town flooded", "occurred_at": "04/03/2026"}
    ).extract(TEXT)

    assert event.occurred_at is None
    assert event.metadata == {"occurred_at_text": "04/03/2026"}


async def test_malformed_items_are_skipped(caplog: pytest.LogCaptureFixture) -> None:
    events = await provider(
        "not an object",
        {"title": "No type"},
        {"event_type": "flood"},
        {"event_type": "flood", "title": ["a", "list"]},
        {"event_type": "x" * 51, "title": "Type too long"},
        {"event_type": "flood", "title": "Town flooded"},
    ).extract(TEXT)

    assert [event.title for event in events] == ["Town flooded"]
    assert caplog.text.count("Skipped extracted event") == 5


@pytest.mark.parametrize("output", [{}, {"event": "flood"}, {"event": None}])
async def test_response_without_an_event_list_fails(output: Any) -> None:
    with pytest.raises(InvalidExtractedEventError, match="no list of events"):
        await Gliner2EventProvider(FakeBackend(output)).extract(TEXT)


async def test_no_events() -> None:
    assert await provider().extract(TEXT) == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-03-04", datetime(2026, 3, 4, tzinfo=UTC)),
        (
            "2026-03-04T10:30:00+02:00",
            datetime(2026, 3, 4, 10, 30, tzinfo=timezone(timedelta(hours=2))),
        ),
        ("2026-03-04T10:30:00Z", datetime(2026, 3, 4, 10, 30, tzinfo=UTC)),
        ("4 March 2026", datetime(2026, 3, 4, tzinfo=UTC)),
        ("March 4, 2026", datetime(2026, 3, 4, tzinfo=UTC)),
        ("march 4 2026", datetime(2026, 3, 4, tzinfo=UTC)),
    ],
)
def test_certain_dates_are_parsed(value: str, expected: datetime) -> None:
    assert parse_event_time(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "04/03/2026",
        "2026-03-04T10:30:00",
        "yesterday",
        "March 2026",
        "31 February 2026",
        "4 Mars 2026",
        "20260304",
    ],
    ids=[
        "day and month order unknown",
        "no time zone",
        "relative",
        "no day",
        "no such day",
        "unknown month name",
        "compact",
    ],
)
def test_unclear_dates_are_not_guessed(value: str) -> None:
    assert parse_event_time(value) is None
