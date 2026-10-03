import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from signalscope.evaluation.bundle import (
    BundleEntry,
    _validate_archive_paths,
    bundle_evaluation_reports,
)
from signalscope.evaluation.dataset import EvaluationDataError


def _report(path: Path, task: str = "reranking") -> None:
    path.write_text(
        json.dumps(
            {
                "report_version": 1,
                "task": task,
                "model": "fake-model",
                "provider": "fake",
                "dataset": {"name": "fixed", "fingerprint": "a" * 64},
                "metrics": {"score": 0.8},
                "timings": {"wall_seconds": 1.0},
            }
        ),
        encoding="utf-8",
    )


def test_bundles_reports_and_optional_evidence_deterministically(tmp_path: Path) -> None:
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    environment, gate = tmp_path / "environment.json", tmp_path / "gate.json"
    _report(first)
    _report(second, "answer_citation")
    environment.write_text('{"platform":"test"}', encoding="utf-8")
    gate.write_text('{"passed":true}', encoding="utf-8")
    output = tmp_path / "bundle.zip"
    created = datetime(2026, 10, 3, tzinfo=UTC)

    manifest = bundle_evaluation_reports(
        output, [first, second], created_at=created, environment=environment, gate_results=[gate]
    )
    first_bytes = output.read_bytes()
    bundle_evaluation_reports(
        output, [first, second], created_at=created, environment=environment, gate_results=[gate]
    )

    assert output.read_bytes() == first_bytes
    assert [item["task"] for item in manifest["files"][:2]] == [
        "reranking",
        "answer_citation",
    ]
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == [
            "manifest.json",
            "reports/report-001.json",
            "reports/report-002.json",
            "environment.json",
            "quality-gates/result-001.json",
        ]
        stored = json.loads(archive.read("manifest.json"))
        for item in stored["files"]:
            assert item["sha256"] == hashlib.sha256(archive.read(item["path"])).hexdigest()


def test_single_report_bundle_is_valid(tmp_path: Path) -> None:
    report, output = tmp_path / "report.json", tmp_path / "bundle.zip"
    _report(report)
    bundle_evaluation_reports(output, [report], created_at=datetime(2026, 10, 3, tzinfo=UTC))
    with zipfile.ZipFile(output) as archive:
        assert "reports/report-001.json" in archive.namelist()


def test_rejects_bad_report(tmp_path: Path) -> None:
    report = tmp_path / "bad.json"
    report.write_text('{"report_version":1}', encoding="utf-8")
    with pytest.raises(EvaluationDataError, match="not valid"):
        bundle_evaluation_reports(
            tmp_path / "bundle.zip", [report], created_at=datetime(2026, 10, 3, tzinfo=UTC)
        )


@pytest.mark.parametrize("path", ["../report.json", "/report.json", "reports\\bad.json"])
def test_rejects_unsafe_archive_path(path: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsafe"):
        _validate_archive_paths([BundleEntry(tmp_path / "report.json", path, "report")])


def test_rejects_duplicate_archive_path(tmp_path: Path) -> None:
    entries = [
        BundleEntry(tmp_path / "one.json", "reports/report.json", "report"),
        BundleEntry(tmp_path / "two.json", "reports/report.json", "report"),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        _validate_archive_paths(entries)
