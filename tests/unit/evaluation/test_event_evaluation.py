from datetime import UTC, datetime, timedelta, timezone

import pytest

from signalscope.evaluation.extraction.dataset import (
    ExtractionDataset,
    ExtractionDocument,
    GoldEvent,
)
from signalscope.evaluation.extraction.events import evaluate_events
from signalscope.evaluation.extraction.scoring import ExtractionScore
from signalscope.events.provider import ExtractedEvent

pytestmark = pytest.mark.anyio

MARCH_4 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


class ScriptedEvents:
    """Returns fixed events for each document text."""

    provider_name = "test"
    model_name = "scripted"

    def __init__(self, answers: dict[str, list[ExtractedEvent]]) -> None:
        self.answers = answers

    async def extract(self, text: str) -> list[ExtractedEvent]:
        return self.answers.get(text, [])


DATASET = ExtractionDataset(
    name="floods",
    documents=(
        ExtractionDocument("a", "The river flooded Porto."),
        ExtractionDocument("b", "Voters chose a mayor."),
    ),
    events=(
        GoldEvent("a", "flood", "Porto flooded", MARCH_4),
        GoldEvent("b", "election", "Mayor elected"),
    ),
)


async def score(**answers: list[ExtractedEvent]) -> ExtractionScore:
    texts = {document.key: document.text for document in DATASET.documents}
    return await evaluate_events(
        DATASET, ScriptedEvents({texts[key]: events for key, events in answers.items()})
    )


def flood(**values: object) -> ExtractedEvent:
    return ExtractedEvent(**({"event_type": "flood", "title": "Porto flooded"} | values))  # type: ignore[arg-type]


def election() -> ExtractedEvent:
    return ExtractedEvent(event_type="election", title="Mayor elected")


async def test_perfect() -> None:
    result = await score(a=[flood(occurred_at=MARCH_4)], b=[election()])

    assert (result.dataset, result.kind, result.provider, result.model) == (
        "floods",
        "event",
        "test",
        "scripted",
    )
    assert (result.document_count, result.gold_count, result.predicted_count) == (2, 2, 2)
    assert (result.matched_count, result.precision, result.recall, result.f1) == (2, 1.0, 1.0, 1.0)


async def test_missing_event() -> None:
    result = await score(a=[flood()])

    assert (result.precision, result.recall) == (1.0, 0.5)
    assert result.f1 == pytest.approx(2 / 3)
    [_, second] = result.documents
    assert (second.document_key, second.missed, second.extra) == (
        "b",
        ("election: Mayor elected",),
        (),
    )


async def test_extra_event() -> None:
    result = await score(a=[flood(), flood(title="Bridge closed")], b=[election()])

    assert (result.matched_count, result.predicted_count) == (2, 3)
    assert result.precision == pytest.approx(2 / 3)
    assert result.documents[0].extra == ("flood: Bridge closed",)


async def test_repeated_prediction_matches_once() -> None:
    result = await score(a=[flood(), flood()], b=[election()])

    assert (result.matched_count, result.predicted_count) == (2, 3)


async def test_wrong_type() -> None:
    result = await score(a=[flood(event_type="storm")], b=[election()])

    assert result.matched_count == 1


async def test_type_and_title_are_normalized() -> None:
    result = await score(a=[flood(event_type=" FLOOD ", title="porto   FLOODED")], b=[election()])

    assert result.matched_count == 2


async def test_dates_compare_by_utc_day() -> None:
    late = datetime(2026, 3, 5, 1, 0, tzinfo=timezone(timedelta(hours=2)))

    same_day = await score(a=[flood(occurred_at=late)], b=[election()])
    other_day = await score(a=[flood(occurred_at=MARCH_4 + timedelta(days=1))], b=[election()])
    no_date = await score(a=[flood()], b=[election()])

    assert (same_day.matched_count, other_day.matched_count, no_date.matched_count) == (2, 1, 2)


async def test_empty_predictions() -> None:
    result = await score()

    assert (result.predicted_count, result.matched_count) == (0, 0)
    assert (result.precision, result.recall, result.f1) == (None, 0.0, None)


async def test_no_gold_and_no_predictions() -> None:
    empty = ExtractionDataset("empty", (ExtractionDocument("a", "Nothing happened."),))

    result = await evaluate_events(empty, ScriptedEvents({}))

    assert (result.precision, result.recall, result.f1) == (None, None, None)
