import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Protocol

from signalscope.core.errors import ServiceUnavailableError, SignalScopeError
from signalscope.domain.events.model import EVENT_TITLE_MAX_LENGTH, EVENT_TYPE_MAX_LENGTH


class EventExtractorUnavailableError(ServiceUnavailableError):
    default_message = "Event extraction model is not available."


class InvalidExtractedEventError(SignalScopeError):
    """The model answered with an event that cannot be stored."""

    default_message = "Event extraction returned an invalid event."


@dataclass(frozen=True, slots=True)
class ExtractedEvent:
    # A short label, such as "election" or "flood".
    event_type: str
    title: str
    summary: str | None = None
    # When the event happened, with a time zone, when the text says.
    occurred_at: datetime | None = None
    # How sure the model is, from 0 to 1, when it says.
    confidence: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class EventExtractionProvider(Protocol):
    """Finds the events a text reports, with one model."""

    provider_name: str
    model_name: str

    async def extract(self, text: str) -> list[ExtractedEvent]:
        """Return the events text reports. A text may report none."""
        ...


async def extract_events(provider: EventExtractionProvider, text: str) -> list[ExtractedEvent]:
    """Extract events with provider and check each one before it is stored.

    Event types come back trimmed and in lower case, and titles trimmed.
    """
    if not text.strip():
        return []
    events = await provider.extract(text)
    name = f"{provider.provider_name}/{provider.model_name}"
    checked = []
    for event in events:
        problem = event_problem(event)
        if problem is not None:
            raise InvalidExtractedEventError(f"Event extraction model {name} {problem}.")
        checked.append(
            replace(event, event_type=event.event_type.strip().lower(), title=event.title.strip())
        )
    return checked


def event_problem(event: ExtractedEvent) -> str | None:
    """Say what is wrong with an extracted event, or return None when it can be stored."""
    if not isinstance(event.event_type, str) or not event.event_type.strip():
        return "returned an event without a type"
    if len(event.event_type.strip()) > EVENT_TYPE_MAX_LENGTH:
        return f"returned an event type longer than {EVENT_TYPE_MAX_LENGTH} characters"
    if not isinstance(event.title, str) or not event.title.strip():
        return "returned an event without a title"
    if len(event.title.strip()) > EVENT_TITLE_MAX_LENGTH:
        return f"returned an event title longer than {EVENT_TITLE_MAX_LENGTH} characters"
    if event.summary is not None and not isinstance(event.summary, str):
        return "returned a summary that is not text"
    if event.occurred_at is not None and (
        not isinstance(event.occurred_at, datetime) or event.occurred_at.utcoffset() is None
    ):
        return "returned a time without a time zone"
    confidence = event.confidence
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, int | float)
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        return "returned a confidence outside 0 to 1"
    if not isinstance(event.metadata, Mapping):
        return "returned metadata that is not an object"
    return None
