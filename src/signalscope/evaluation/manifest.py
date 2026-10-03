import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from signalscope.evaluation.dataset import EvaluationDataError

DatasetTask = Literal[
    "embedding_retrieval",
    "reranking",
    "structured_extraction",
    "answer_citation",
]

DATASET_MANIFEST_VERSION = 1
DATASET_TASKS = {
    "embedding_retrieval",
    "reranking",
    "structured_extraction",
    "answer_citation",
}


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    manifest_version: int
    name: str
    version: str
    task: DatasetTask
    created_at: str
    record_count: int
    content_sha256: str
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_dataset_manifest(path: Path) -> DatasetManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError
        manifest = DatasetManifest(
            manifest_version=raw["manifest_version"],
            name=raw["name"],
            version=raw["version"],
            task=cast(DatasetTask, raw["task"]),
            created_at=raw["created_at"],
            record_count=raw["record_count"],
            content_sha256=raw["content_sha256"],
            notes=raw.get("notes"),
        )
        validate_dataset_manifest(manifest)
        return manifest
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise EvaluationDataError(f"Dataset manifest {path} is not valid.") from None


def validate_dataset_manifest(
    manifest: DatasetManifest,
    *,
    expected_task: DatasetTask | None = None,
    record_count: int | None = None,
    content: bytes | None = None,
) -> None:
    if manifest.manifest_version != DATASET_MANIFEST_VERSION:
        raise ValueError("Unsupported dataset manifest version.")
    if not manifest.name.strip() or not manifest.version.strip():
        raise ValueError("Dataset name and version are required.")
    if manifest.task not in DATASET_TASKS:
        raise ValueError("Dataset task is not valid.")
    try:
        datetime.fromisoformat(manifest.created_at)
    except ValueError:
        raise ValueError("Dataset creation time is not valid.") from None
    if manifest.record_count < 0:
        raise ValueError("Dataset record count cannot be negative.")
    if len(manifest.content_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in manifest.content_sha256
    ):
        raise ValueError("Dataset content fingerprint is not valid.")
    if manifest.notes is not None and not isinstance(manifest.notes, str):
        raise ValueError("Dataset notes must be text.")
    if expected_task is not None and manifest.task != expected_task:
        raise ValueError(f"Dataset task is {manifest.task}; expected {expected_task}.")
    if record_count is not None and manifest.record_count != record_count:
        raise ValueError(
            f"Dataset has {record_count} records; manifest declares {manifest.record_count}."
        )
    if content is not None and manifest.content_sha256 != fingerprint_content(content):
        raise ValueError("Dataset content fingerprint does not match the manifest.")


def fingerprint_content(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
