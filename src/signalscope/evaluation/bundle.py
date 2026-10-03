import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from signalscope.evaluation.dataset import EvaluationDataError

BUNDLE_FORMAT_VERSION = 1
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class BundleEntry:
    source: Path
    archive_path: str
    kind: str


def bundle_evaluation_reports(
    output: Path,
    reports: list[Path],
    *,
    created_at: datetime,
    environment: Path | None = None,
    gate_results: list[Path] | None = None,
) -> dict[str, Any]:
    if not reports:
        raise ValueError("At least one evaluation report is required.")
    entries = [
        BundleEntry(path, f"reports/report-{index:03d}.json", "evaluation_report")
        for index, path in enumerate(reports, 1)
    ]
    if environment is not None:
        entries.append(BundleEntry(environment, "environment.json", "environment_report"))
    entries.extend(
        BundleEntry(path, f"quality-gates/result-{index:03d}.json", "quality_gate_result")
        for index, path in enumerate(gate_results or [], 1)
    )
    _validate_archive_paths(entries)
    loaded = [(entry, _load_json(entry.source)) for entry in entries]
    for entry, value in loaded:
        if entry.kind == "evaluation_report":
            _validate_report(entry.source, value)
    files = []
    for entry, value in loaded:
        data = _canonical_json(value)
        metadata: dict[str, Any] = {
            "path": entry.archive_path,
            "kind": entry.kind,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if entry.kind == "evaluation_report":
            metadata.update(
                task=value["task"],
                model=value.get("model"),
                provider=value.get("provider"),
                dataset_fingerprint=value["dataset"]["fingerprint"],
            )
        files.append(metadata)
    manifest = {
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "created_at": created_at.isoformat(),
        "files": files,
    }
    members = [("manifest.json", _canonical_json(manifest))]
    members.extend((entry.archive_path, _canonical_json(value)) for entry, value in loaded)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in members:
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return manifest


def _validate_archive_paths(entries: list[BundleEntry]) -> None:
    paths = [entry.archive_path for entry in entries]
    if len(paths) != len(set(paths)):
        raise ValueError("Evaluation bundle contains duplicate archive paths.")
    for path in paths:
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or ".." in parsed.parts or "\\" in path:
            raise ValueError(f"Unsafe evaluation bundle path: {path}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError
        return value
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        raise EvaluationDataError(f"Evaluation artifact {path} is not valid JSON.") from None


def _validate_report(path: Path, report: dict[str, Any]) -> None:
    try:
        if report["report_version"] != 1:
            raise TypeError
        if not all(isinstance(report[field], str) for field in ("task", "model", "provider")):
            raise TypeError
        if not isinstance(report["dataset"]["fingerprint"], str):
            raise TypeError
        if not isinstance(report["metrics"], dict) or not isinstance(report["timings"], dict):
            raise TypeError
    except (KeyError, TypeError):
        raise EvaluationDataError(f"Evaluation report {path} is not valid.") from None


def _canonical_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
