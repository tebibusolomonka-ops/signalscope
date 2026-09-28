from datetime import UTC, datetime
from typing import Any

import pytest

from signalscope.evaluation.dataset import EvaluationDataError
from signalscope.evaluation.extraction.dataset import (
    ExtractionDataset,
    ExtractionDocument,
    GoldClaim,
    GoldEvent,
)

TEXT = "The river flooded Porto on 4 March 2026. Prices rose 5%."


def dataset(**values: Any) -> ExtractionDataset:
    fields: dict[str, Any] = {
        "name": "floods",
        "documents": (ExtractionDocument("flood-1", TEXT, "en"),),
        "events": (
            GoldEvent("flood-1", "flood", "Porto flooded", datetime(2026, 3, 4, tzinfo=UTC)),
        ),
        "claims": (GoldClaim("flood-1", "statistic", "Prices rose 5%", 41, 55),),
    }
    return ExtractionDataset(**(fields | values))


def test_valid_dataset() -> None:
    found = dataset()

    assert found.document("flood-1").language == "en"
    assert [event.title for event in found.events] == ["Porto flooded"]
    assert [claim.surface_text for claim in found.claims] == ["Prices rose 5%"]


def test_gold_lists_are_optional() -> None:
    found = ExtractionDataset("empty", [ExtractionDocument("a", "Text.")])  # type: ignore[arg-type]

    assert (found.documents, found.events, found.claims) == (
        (ExtractionDocument("a", "Text."),),
        (),
        (),
    )


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"documents": ()}, "has no documents"),
        (
            {"documents": (ExtractionDocument("a", "One."), ExtractionDocument("a", "Two."))},
            "document key 'a' twice",
        ),
        ({"events": (GoldEvent("other", "flood", "Porto flooded"),)}, "no document 'other'"),
        (
            {"claims": (GoldClaim("other", "statistic", "Prices", 0, 6),)},
            "no document 'other'",
        ),
        (
            {"claims": (GoldClaim("flood-1", "statistic", "Prices", 50, 99),)},
            "offsets 50:99 outside",
        ),
        (
            {"claims": (GoldClaim("flood-1", "statistic", "Prices", 5, 5),)},
            "offsets 5:5 outside",
        ),
        (
            {"claims": (GoldClaim("flood-1", "statistic", "Prices", 0, 6),)},
            "not at offsets 0:6",
        ),
        ({"name": " "}, "Dataset name must not be empty"),
    ],
    ids=[
        "no documents",
        "duplicate document",
        "event unknown document",
        "claim unknown document",
        "offsets outside",
        "empty span",
        "surface mismatch",
        "blank name",
    ],
)
def test_invalid_dataset(values: dict[str, Any], message: str) -> None:
    with pytest.raises(EvaluationDataError, match=message):
        dataset(**values)


@pytest.mark.parametrize(
    "build",
    [
        lambda: ExtractionDocument(" ", "Text."),
        lambda: ExtractionDocument("a", " "),
        lambda: ExtractionDocument("a", "Text.", " "),
        lambda: GoldEvent("a", " ", "Title"),
        lambda: GoldEvent("a", "flood", ""),
        lambda: GoldEvent("a", "flood", "Title", datetime(2026, 3, 4)),
        lambda: GoldClaim("a", " ", "Prices", 0, 6),
        lambda: GoldClaim("a", "statistic", " ", 0, 1),
    ],
    ids=[
        "blank key",
        "blank text",
        "blank language",
        "blank event type",
        "blank title",
        "date without zone",
        "blank claim type",
        "blank claim text",
    ],
)
def test_blank_values(build: Any) -> None:
    with pytest.raises(EvaluationDataError):
        build()
