"""Reads a retrieval dataset from a local JSON file.

The file holds one object:

    {
      "name": "media-smoke",
      "documents": [{"key": "energy-1", "title": "...", "text": "...", "language": "en"}],
      "queries": [{"key": "q1", "text": "...", "relevant_documents": ["energy-1"]}]
    }

title and language are optional. Other fields are rejected, so a typo does
not silently drop data.
"""

import json
from pathlib import Path
from typing import Any

from signalscope.evaluation.dataset import (
    EvaluationDataError,
    EvaluationDocument,
    EvaluationQuery,
    RetrievalDataset,
)

MAX_DATASET_BYTES = 20 * 1024 * 1024
MAX_DOCUMENTS = 10_000
MAX_QUERIES = 5_000

DATASET_FIELDS = frozenset({"name", "documents", "queries"})
DOCUMENT_FIELDS = frozenset({"key", "text", "title", "language"})
QUERY_FIELDS = frozenset({"key", "text", "relevant_documents"})


def load_dataset(path: Path) -> RetrievalDataset:
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
    return parse_dataset(data, str(path))


def parse_dataset(data: bytes, origin: str) -> RetrievalDataset:
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
    fields = _object(raw, f"Dataset {origin}", DATASET_FIELDS, DATASET_FIELDS)
    name = _string(fields, "name", f"Dataset {origin}")
    documents = _list(fields, "documents", f"Dataset {name!r}", MAX_DOCUMENTS)
    queries = _list(fields, "queries", f"Dataset {name!r}", MAX_QUERIES)
    return RetrievalDataset(
        name=name,
        documents=tuple(
            _document(item, f"Dataset {name!r} documents[{index}]")
            for index, item in enumerate(documents)
        ),
        queries=tuple(
            _query(item, f"Dataset {name!r} queries[{index}]") for index, item in enumerate(queries)
        ),
    )


def _document(raw: Any, where: str) -> EvaluationDocument:
    fields = _object(raw, where, DOCUMENT_FIELDS, {"key", "text"})
    return EvaluationDocument(
        key=_string(fields, "key", where),
        text=_string(fields, "text", where),
        title=_optional_string(fields, "title", where),
        language=_optional_string(fields, "language", where),
    )


def _query(raw: Any, where: str) -> EvaluationQuery:
    fields = _object(raw, where, QUERY_FIELDS, QUERY_FIELDS)
    relevant = fields["relevant_documents"]
    if not isinstance(relevant, list) or not all(isinstance(key, str) for key in relevant):
        raise EvaluationDataError(f"{where}: relevant_documents must be a list of keys.")
    return EvaluationQuery(
        key=_string(fields, "key", where),
        text=_string(fields, "text", where),
        relevant_documents=frozenset(relevant),
    )


def _object(
    raw: Any, where: str, allowed: frozenset[str], required: set[str] | frozenset[str]
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise EvaluationDataError(f"{where} must be a JSON object.")
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise EvaluationDataError(f"{where} has unknown fields: {', '.join(unknown)}.")
    missing = sorted(set(required) - set(raw))
    if missing:
        raise EvaluationDataError(f"{where} is missing fields: {', '.join(missing)}.")
    return raw


def _string(fields: dict[str, Any], name: str, where: str) -> str:
    value = fields[name]
    if not isinstance(value, str):
        raise EvaluationDataError(f"{where}: {name} must be text.")
    return value


def _optional_string(fields: dict[str, Any], name: str, where: str) -> str | None:
    if fields.get(name) is None:
        return None
    return _string(fields, name, where)


def _list(fields: dict[str, Any], name: str, where: str, most: int) -> list[Any]:
    value = fields[name]
    if not isinstance(value, list):
        raise EvaluationDataError(f"{where}: {name} must be a list.")
    if len(value) > most:
        raise EvaluationDataError(f"{where} has more than {most} {name}.")
    return value
