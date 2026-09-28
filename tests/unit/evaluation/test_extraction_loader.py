import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from signalscope.evaluation.dataset import EvaluationDataError
from signalscope.evaluation.extraction.dataset import (
    ExtractionDataset,
    ExtractionDocument,
    GoldRelation,
)
from signalscope.evaluation.extraction.loader import (
    load_extraction_dataset,
    parse_extraction_dataset,
)

TEXT = "Ana Silva works for Acme. Prices rose 5%."


def raw(**values: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": "media",
        "documents": [{"key": "a", "text": TEXT, "language": "en"}],
        "events": [
            {
                "document_key": "a",
                "event_type": "hiring",
                "title": "Ana joined Acme",
                "occurred_at": "2026-03-04T00:00:00+00:00",
            }
        ],
        "claims": [
            {
                "document_key": "a",
                "claim_type": "statistic",
                "surface_text": "Prices rose 5%",
                "start_char": 26,
                "end_char": 40,
            }
        ],
        "relations": [
            {
                "document_key": "a",
                "subject_text": "Ana Silva",
                "relation_type": "works_for",
                "object_text": "Acme",
                "subject_start": 0,
                "subject_end": 9,
            }
        ],
    }
    return data | values


def parse(data: dict[str, Any]) -> ExtractionDataset:
    return parse_extraction_dataset(json.dumps(data).encode(), "test.json")


def test_load_from_a_file(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text(json.dumps(raw()), encoding="utf-8")

    dataset = load_extraction_dataset(path)

    assert dataset.name == "media"
    assert dataset.events[0].occurred_at == datetime(2026, 3, 4, tzinfo=UTC)
    assert dataset.claims[0].surface_text == "Prices rose 5%"
    assert dataset.relations == (
        GoldRelation("a", "Ana Silva", "works_for", "Acme", subject_start=0, subject_end=9),
    )


def test_gold_lists_are_optional() -> None:
    dataset = parse({"name": "only-documents", "documents": [{"key": "a", "text": TEXT}]})

    assert (dataset.events, dataset.claims, dataset.relations) == ((), (), ())


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (raw(extra=1), "unknown fields: extra"),
        (
            raw(relations=[{"document_key": "a", "relation_type": "x", "object_text": "y"}]),
            "missing fields: subject_text",
        ),
        (raw(relations="none"), "relations must be a list"),
        (
            raw(claims=[raw()["claims"][0] | {"start_char": "26"}]),
            "start_char must be a whole number",
        ),
        (raw(events=[raw()["events"][0] | {"occurred_at": "March"}]), "ISO 8601"),
        (raw(events=[raw()["events"][0] | {"occurred_at": "2026-03-04T00:00:00"}]), "time zone"),
    ],
    ids=["unknown field", "missing field", "not a list", "offset text", "bad date", "no zone"],
)
def test_bad_files(data: dict[str, Any], message: str) -> None:
    with pytest.raises(EvaluationDataError, match=message):
        parse(data)


def test_not_json() -> None:
    with pytest.raises(EvaluationDataError, match="not valid JSON"):
        parse_extraction_dataset(b"{", "test.json")


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(EvaluationDataError, match="Cannot read"):
        load_extraction_dataset(tmp_path / "missing.json")


def dataset_with(*relations: GoldRelation) -> ExtractionDataset:
    return ExtractionDataset("r", (ExtractionDocument("a", TEXT),), relations=relations)


def test_valid_relations() -> None:
    found = dataset_with(
        GoldRelation("a", "Ana Silva", "works_for", "Acme"),
        GoldRelation("a", "Ana Silva", "works_for", "Acme", 0, 9, 20, 24),
    )

    assert len(found.relations) == 2


@pytest.mark.parametrize(
    ("relation", "message"),
    [
        (GoldRelation("b", "Ana Silva", "works_for", "Acme"), "no document 'b'"),
        (GoldRelation("a", "Ana Silva", "works_for", "Acme", subject_start=0), "both offsets"),
        (
            GoldRelation("a", "Ana Silva", "works_for", "Acme", 0, 3),
            "subject .* not at offsets 0:3",
        ),
        (
            GoldRelation("a", "Ana Silva", "works_for", "Acme", object_start=20, object_end=99),
            "object .* not at offsets 20:99",
        ),
    ],
    ids=["unknown document", "one offset", "subject mismatch", "object outside"],
)
def test_invalid_relations(relation: GoldRelation, message: str) -> None:
    with pytest.raises(EvaluationDataError, match=message):
        dataset_with(relation)


@pytest.mark.parametrize(
    "values",
    [("a", " ", "works_for", "Acme"), ("a", "Ana", "", "Acme"), ("a", "Ana", "works_for", " ")],
    ids=["blank subject", "blank type", "blank object"],
)
def test_blank_relation_fields(values: tuple[str, str, str, str]) -> None:
    with pytest.raises(EvaluationDataError):
        GoldRelation(*values)
