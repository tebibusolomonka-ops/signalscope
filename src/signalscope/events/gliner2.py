"""Event extraction with the shared local GLiNER2 model."""

import logging
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from typing import Any, Protocol

from signalscope.events.provider import ExtractedEvent, InvalidExtractedEventError, event_problem
from signalscope.extraction.gliner2 import StructuredSchema, field_text

logger = logging.getLogger(__name__)

EVENT_RECORD = "event"
EVENT_SCHEMA: StructuredSchema = {
    EVENT_RECORD: (
        "event_type::str::The kind of event in one or two words, such as election or flood",
        "title::str::A short name for what happened",
        "summary::str::One sentence about what happened",
        "occurred_at::str::The date or time the event happened, as written in the text",
    )
}

MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}
DAY_MONTH_YEAR = re.compile(r"(\d{1,2}) ([a-z]+) (\d{4})")
MONTH_DAY_YEAR = re.compile(r"([a-z]+) (\d{1,2}),? (\d{4})")


class StructuredBackend(Protocol):
    provider_name: str
    model_name: str

    async def extract_json(self, text: str, schema: StructuredSchema) -> dict[str, Any]: ...


class Gliner2EventProvider:
    """Finds events with GLiNER2 structured extraction.

    GLiNER2 gives no score for a whole record, so confidence stays None. A
    record without a type or title, or one that cannot be stored, is skipped
    with a warning, so one bad record does not lose the others. A response
    without a list of events fails.
    """

    def __init__(self, backend: StructuredBackend) -> None:
        self.backend = backend
        self.provider_name = backend.provider_name
        self.model_name = backend.model_name

    async def extract(self, text: str) -> list[ExtractedEvent]:
        output = await self.backend.extract_json(text, EVENT_SCHEMA)
        records = output.get(EVENT_RECORD)
        if not isinstance(records, list):
            raise InvalidExtractedEventError(
                f"Event extraction model {self.provider_name}/{self.model_name} "
                "returned no list of events."
            )
        events = []
        for index, record in enumerate(records):
            event = _event(record)
            problem = "is not a usable event" if event is None else event_problem(event)
            if event is None or problem is not None:
                logger.warning("Skipped extracted event %s: %s", index, problem)
                continue
            events.append(event)
        return events


def _event(record: Any) -> ExtractedEvent | None:
    if not isinstance(record, Mapping):
        return None
    event_type = field_text(record, "event_type")
    title = field_text(record, "title")
    if event_type is None or title is None:
        return None
    written = field_text(record, "occurred_at")
    return ExtractedEvent(
        event_type=event_type,
        title=title,
        summary=field_text(record, "summary"),
        occurred_at=None if written is None else parse_event_time(written),
        # The date as the model read it, kept even when it could not be parsed.
        metadata={} if written is None else {"occurred_at_text": written},
    )


def parse_event_time(value: str) -> datetime | None:
    """Parse a date or time only when its meaning is certain.

    Accepted: ISO 8601 times with a time zone, ISO dates such as 2026-03-04,
    and English dates that name the month, such as 4 March 2026. A date alone
    becomes midnight UTC. Everything else gives None, including 04/03/2026,
    whose day and month order is unknown, and times without a time zone.
    """
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return _named_month_date(value.lower())
    if len(value) == len("2026-03-04"):
        return datetime.combine(parsed.date(), time(), tzinfo=UTC)
    if parsed.utcoffset() is None:
        return None
    return parsed


def _named_month_date(value: str) -> datetime | None:
    if match := DAY_MONTH_YEAR.fullmatch(value):
        day, month, year = match.group(1), match.group(2), match.group(3)
    elif match := MONTH_DAY_YEAR.fullmatch(value):
        month, day, year = match.group(1), match.group(2), match.group(3)
    else:
        return None
    if month not in MONTHS:
        return None
    try:
        found = date(int(year), MONTHS[month], int(day))
    except ValueError:
        return None
    return datetime.combine(found, time(), tzinfo=UTC)
