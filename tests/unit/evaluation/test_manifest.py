import json
from pathlib import Path

import pytest

from signalscope.evaluation.manifest import (
    DatasetManifest,
    fingerprint_content,
    load_dataset_manifest,
    validate_dataset_manifest,
)


def _manifest(content: bytes = b"records") -> DatasetManifest:
    return DatasetManifest(
        manifest_version=1,
        name="small retrieval set",
        version="1.0",
        task="embedding_retrieval",
        created_at="2026-10-03T10:00:00+00:00",
        record_count=2,
        content_sha256=fingerprint_content(content),
        notes="Fixed test cases.",
    )


def test_loads_valid_manifest(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest().to_dict()), encoding="utf-8")

    loaded = load_dataset_manifest(path)

    assert loaded.name == "small retrieval set"
    validate_dataset_manifest(
        loaded,
        expected_task="embedding_retrieval",
        record_count=2,
        content=b"records",
    )


def test_refuses_wrong_task() -> None:
    with pytest.raises(ValueError, match="expected reranking"):
        validate_dataset_manifest(_manifest(), expected_task="reranking")


def test_refuses_wrong_record_count() -> None:
    with pytest.raises(ValueError, match="manifest declares 2"):
        validate_dataset_manifest(_manifest(), record_count=3)


def test_content_fingerprint_changes() -> None:
    assert fingerprint_content(b"first") != fingerprint_content(b"second")


def test_refuses_changed_content() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validate_dataset_manifest(_manifest(b"first"), content=b"second")
