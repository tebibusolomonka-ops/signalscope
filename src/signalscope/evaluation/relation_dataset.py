import hashlib
import json
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from signalscope.evaluation.dataset import EvaluationDataError


@dataclass(frozen=True, slots=True)
class RelationTriple:
    subject: str
    relation_type: str
    object: str
    evidence_span: dict[str, int] | None = None


@dataclass(frozen=True, slots=True)
class RelationExample:
    key: str
    text: str | None
    evidence_reference: str | None
    mentions: tuple[str, ...]
    relations: tuple[RelationTriple, ...]


@dataclass(frozen=True, slots=True)
class RelationDataset:
    format_version: int
    name: str
    version: str
    examples: tuple[RelationExample, ...]

    def fingerprint(self) -> str:
        data = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()


def load_relation_dataset(path: Path) -> RelationDataset:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["format_version"] != 1:
            raise TypeError
        examples = tuple(_example(item) for item in raw["examples"])
        dataset = RelationDataset(1, _text(raw["name"]), _text(raw["version"]), examples)
        if not examples:
            raise ValueError("Relation dataset must contain examples.")
        keys = [item.key for item in examples]
        if len(keys) != len(set(keys)):
            raise ValueError("Relation example keys must be unique.")
        return dataset
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError):
            message = str(error)
        else:
            message = f"Relation dataset {path} is not valid."
        raise EvaluationDataError(message) from None


def normalize_relation_part(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _example(raw: dict[str, Any]) -> RelationExample:
    key = _text(raw["key"])
    text = raw.get("text")
    reference = raw.get("evidence_reference")
    if (text is None) == (reference is None):
        raise ValueError(f"Relation example {key!r} needs text or one evidence reference.")
    text = None if text is None else _text(text)
    reference = None if reference is None else _text(reference)
    mentions = tuple(_text(value) for value in raw.get("mentions", []))
    relations = tuple(_triple(value) for value in raw["relations"])
    normalized = [
        (
            normalize_relation_part(item.subject),
            normalize_relation_part(item.relation_type),
            normalize_relation_part(item.object),
        )
        for item in relations
    ]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"Relation example {key!r} has duplicate expected relations.")
    return RelationExample(key, text, reference, mentions, relations)


def _triple(raw: dict[str, Any]) -> RelationTriple:
    span = raw.get("evidence_span")
    if span is not None:
        if set(span) != {"start", "end"} or not all(
            isinstance(span[name], int) and not isinstance(span[name], bool)
            for name in ("start", "end")
        ):
            raise ValueError("Relation evidence span is not valid.")
        if not 0 <= span["start"] < span["end"]:
            raise ValueError("Relation evidence span is not valid.")
    return RelationTriple(
        _text(raw["subject"]),
        _text(raw["relation_type"]),
        _text(raw["object"]),
        span,
    )


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Relation dataset text fields must not be empty.")
    return unicodedata.normalize("NFC", value.strip())
