"""Reads an extraction dataset from a local JSON file.

The file holds one object:

    {
      "name": "media-extraction",
      "documents": [{"key": "flood-1", "text": "...", "language": "en"}],
      "events": [{"document_key": "flood-1", "event_type": "flood",
                  "title": "Porto flooded", "occurred_at": "2026-03-04T00:00:00+00:00"}],
      "claims": [{"document_key": "flood-1", "claim_type": "statistic",
                  "surface_text": "Prices rose 5%", "start_char": 41, "end_char": 55}],
      "relations": [{"document_key": "flood-1", "subject_text": "Ana Silva",
                     "relation_type": "works_for", "object_text": "Acme"}]
    }

events, claims, relations, language and occurred_at are optional, and so are
the relation offsets subject_start, subject_end, object_start and object_end.
Other fields are rejected, so a typo does not silently drop data.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from signalscope.evaluation.dataset import EvaluationDataError
from signalscope.evaluation.extraction.dataset import (
    ExtractionDataset,
    ExtractionDocument,
    GoldClaim,
    GoldEvent,
    GoldRelation,
)
from signalscope.evaluation.loader import (
    MAX_DATASET_BYTES,
    MAX_DOCUMENTS,
    _list,
    _object,
    _optional_string,
    _string,
)

# The most gold items of each kind in one file.
MAX_GOLD_ITEMS = 50_000

DATASET_FIELDS = frozenset({"name", "documents", "events", "claims", "relations"})
DOCUMENT_FIELDS = frozenset({"key", "text", "language"})
EVENT_FIELDS = frozenset({"document_key", "event_type", "title", "occurred_at"})
CLAIM_FIELDS = frozenset({"document_key", "claim_type", "surface_text", "start_char", "end_char"})
RELATION_OFFSETS = ("subject_start", "subject_end", "object_start", "object_end")
RELATION_FIELDS = frozenset(
    {"document_key", "subject_text", "relation_type", "object_text", *RELATION_OFFSETS}
)


def load_extraction_dataset(path: Path) -> ExtractionDataset:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise EvaluationDataError(f"Cannot read dataset file {path}: {error.strerror}") from None
    if size > MAX_DATASET_BYTES:
        raise EvaluationDataError(
            f"Dataset file {path} is larger than {MAX_DATASET_BYTES // (1024 * 1024)} MB."
        )
    try:
        data = path.read_bytes()
    except OSError as error:
        raise EvaluationDataError(f"Cannot read dataset file {path}: {error.strerror}") from None
    return parse_extraction_dataset(data, str(path))


def parse_extraction_dataset(data: bytes, origin: str) -> ExtractionDataset:
    """Build a dataset from JSON bytes. origin names the data in error messages."""
    if len(data) > MAX_DATASET_BYTES:
        raise EvaluationDataError(
            f"Dataset {origin} is larger than {MAX_DATASET_BYTES // (1024 * 1024)} MB."
        )
    try:
        raw = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        raise EvaluationDataError(f"Dataset {origin} is not UTF-8 text.") from None
    except json.JSONDecodeError as error:
        raise EvaluationDataError(
            f"Dataset {origin} is not valid JSON: {error.msg} at line {error.lineno}, "
            f"column {error.colno}."
        ) from None
    fields = _object(raw, f"Dataset {origin}", DATASET_FIELDS, {"name", "documents"})
    name = _string(fields, "name", f"Dataset {origin}")
    where = f"Dataset {name!r}"
    documents = _list(fields, "documents", where, MAX_DOCUMENTS)
    return ExtractionDataset(
        name=name,
        documents=tuple(
            _document(item, f"{where} documents[{index}]") for index, item in enumerate(documents)
        ),
        events=tuple(
            _event(item, f"{where} events[{index}]")
            for index, item in enumerate(_optional_list(fields, "events", where))
        ),
        claims=tuple(
            _claim(item, f"{where} claims[{index}]")
            for index, item in enumerate(_optional_list(fields, "claims", where))
        ),
        relations=tuple(
            _relation(item, f"{where} relations[{index}]")
            for index, item in enumerate(_optional_list(fields, "relations", where))
        ),
    )


def _document(raw: Any, where: str) -> ExtractionDocument:
    fields = _object(raw, where, DOCUMENT_FIELDS, {"key", "text"})
    return ExtractionDocument(
        key=_string(fields, "key", where),
        text=_string(fields, "text", where),
        language=_optional_string(fields, "language", where),
    )


def _event(raw: Any, where: str) -> GoldEvent:
    fields = _object(raw, where, EVENT_FIELDS, {"document_key", "event_type", "title"})
    written = _optional_string(fields, "occurred_at", where)
    occurred_at = None
    if written is not None:
        try:
            occurred_at = datetime.fromisoformat(written)
        except ValueError:
            raise EvaluationDataError(f"{where}: occurred_at must be an ISO 8601 time.") from None
    return GoldEvent(
        document_key=_string(fields, "document_key", where),
        event_type=_string(fields, "event_type", where),
        title=_string(fields, "title", where),
        occurred_at=occurred_at,
    )


def _claim(raw: Any, where: str) -> GoldClaim:
    fields = _object(raw, where, CLAIM_FIELDS, CLAIM_FIELDS)
    return GoldClaim(
        document_key=_string(fields, "document_key", where),
        claim_type=_string(fields, "claim_type", where),
        surface_text=_string(fields, "surface_text", where),
        start_char=_integer(fields, "start_char", where),
        end_char=_integer(fields, "end_char", where),
    )


def _relation(raw: Any, where: str) -> GoldRelation:
    fields = _object(
        raw,
        where,
        RELATION_FIELDS,
        {"document_key", "subject_text", "relation_type", "object_text"},
    )
    offsets = {
        name: None if fields.get(name) is None else _integer(fields, name, where)
        for name in RELATION_OFFSETS
    }
    return GoldRelation(
        document_key=_string(fields, "document_key", where),
        subject_text=_string(fields, "subject_text", where),
        relation_type=_string(fields, "relation_type", where),
        object_text=_string(fields, "object_text", where),
        **offsets,
    )


def _optional_list(fields: dict[str, Any], name: str, where: str) -> list[Any]:
    if fields.get(name) is None:
        return []
    return _list(fields, name, where, MAX_GOLD_ITEMS)


def _integer(fields: dict[str, Any], name: str, where: str) -> int:
    value = fields[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvaluationDataError(f"{where}: {name} must be a whole number.")
    return value
