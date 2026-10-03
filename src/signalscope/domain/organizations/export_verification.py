import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from signalscope.domain.organizations.export_archive import (
    EXPORT_FORMAT_VERSION,
    FILES,
    MANIFEST_FILE,
)

MAX_MANIFEST_BYTES = 1_000_000
MAX_MEMBER_BYTES = 256_000_000
MAX_RECORD_COUNT = 10_000_000
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DATASET_BY_PATH = {path: name for name, path in FILES.items()}


@dataclass(frozen=True, slots=True)
class OrganizationExportVerification:
    valid: bool
    format_version: str | None
    checked_files: int
    checked_records: int
    problems: tuple[str, ...]


class OrganizationExportVerificationService:
    """Verify an organization export without extracting it."""

    def verify(self, data: bytes) -> OrganizationExportVerification:
        problems: list[str] = []
        format_version: str | None = None
        checked_files = 0
        checked_records = 0
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = archive.infolist()
                names = [info.filename for info in infos]
                if len(infos) > len(FILES) + 1:
                    problems.append("Archive contains too many members.")
                for name in names:
                    if not _safe_path(name):
                        problems.append(f"Unsafe archive path: {name}")
                duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
                for name in duplicates:
                    problems.append(f"Duplicate archive path: {name}")
                if names.count(MANIFEST_FILE) != 1:
                    problems.append("Archive must contain exactly one manifest.json file.")
                    return _result(format_version, checked_files, checked_records, problems)
                manifest_info = archive.getinfo(MANIFEST_FILE)
                if manifest_info.file_size > MAX_MANIFEST_BYTES:
                    problems.append("Manifest is too large.")
                    return _result(format_version, checked_files, checked_records, problems)
                try:
                    manifest = json.loads(archive.read(manifest_info))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    problems.append("Manifest is not readable JSON.")
                    return _result(format_version, checked_files, checked_records, problems)
                if not isinstance(manifest, dict):
                    problems.append("Manifest must be a JSON object.")
                    return _result(format_version, checked_files, checked_records, problems)
                raw_version = manifest.get("format_version")
                if isinstance(raw_version, str):
                    format_version = raw_version
                if format_version != EXPORT_FORMAT_VERSION:
                    problems.append("Manifest format version is not supported.")
                entries = _manifest_entries(manifest, problems)
                counts = _record_counts(manifest, problems)
                expected_paths = set(entries)
                actual_paths = set(names) - {MANIFEST_FILE}
                for path in sorted(expected_paths - actual_paths):
                    problems.append(f"Archive member is missing: {path}")
                for path in sorted(actual_paths - expected_paths):
                    problems.append(f"Archive member is not listed in the manifest: {path}")
                for path, entry in entries.items():
                    if path not in actual_paths or path in duplicates or not _safe_path(path):
                        continue
                    info = archive.getinfo(path)
                    if info.file_size > MAX_MEMBER_BYTES:
                        problems.append(f"Archive member is too large: {path}")
                        continue
                    try:
                        content = archive.read(info)
                    except (OSError, RuntimeError, zipfile.BadZipFile):
                        problems.append(f"Archive member could not be read: {path}")
                        continue
                    checked_files += 1
                    if len(content) != entry["size_bytes"]:
                        problems.append(f"Archive member size does not match: {path}")
                    if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                        problems.append(f"Archive member checksum does not match: {path}")
                    records = _read_records(path, content, problems)
                    if records is None:
                        continue
                    checked_records += records
                    dataset = DATASET_BY_PATH.get(path)
                    expected_count = counts.get(dataset) if dataset is not None else None
                    if expected_count is None:
                        problems.append(f"Record count is missing for: {path}")
                    elif records != expected_count:
                        problems.append(f"Record count does not match: {path}")
        except zipfile.BadZipFile:
            problems.append("Archive is not a readable ZIP file.")
        return _result(format_version, checked_files, checked_records, problems)


def _manifest_entries(manifest: dict[str, Any], problems: list[str]) -> dict[str, dict[str, Any]]:
    raw_entries = manifest.get("files")
    if not isinstance(raw_entries, list) or len(raw_entries) > len(FILES):
        problems.append("Manifest files must be a bounded list.")
        return {}
    entries: dict[str, dict[str, Any]] = {}
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            problems.append("Manifest file entry is invalid.")
            continue
        path = raw_entry.get("path")
        size = raw_entry.get("size_bytes")
        checksum = raw_entry.get("sha256")
        if not isinstance(path, str) or path not in DATASET_BY_PATH or not _safe_path(path):
            problems.append("Manifest file path is invalid.")
            continue
        if path in entries:
            problems.append(f"Duplicate manifest file path: {path}")
            continue
        if not isinstance(size, int) or isinstance(size, bool) or not 0 <= size <= MAX_MEMBER_BYTES:
            problems.append(f"Manifest file size is invalid: {path}")
            continue
        if not isinstance(checksum, str) or SHA256_PATTERN.fullmatch(checksum) is None:
            problems.append(f"Manifest file checksum is invalid: {path}")
            continue
        entries[path] = raw_entry
    return entries


def _record_counts(manifest: dict[str, Any], problems: list[str]) -> dict[str, int]:
    raw_counts = manifest.get("record_counts")
    if not isinstance(raw_counts, dict):
        problems.append("Manifest record counts must be an object.")
        return {}
    counts: dict[str, int] = {}
    for name, value in raw_counts.items():
        if (
            name not in FILES
            or not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= MAX_RECORD_COUNT
        ):
            problems.append("Manifest record count is invalid.")
            continue
        counts[name] = value
    return counts


def _read_records(path: str, content: bytes, problems: list[str]) -> int | None:
    try:
        text = content.decode("utf-8")
        if path.endswith(".jsonl"):
            lines = text.splitlines()
            for line in lines:
                json.loads(line)
            return len(lines)
        json.loads(text)
        return 1
    except (UnicodeDecodeError, json.JSONDecodeError):
        problems.append(f"Archive member is not readable JSON: {path}")
        return None


def _safe_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(path)
    return (
        bool(path)
        and not posix.is_absolute()
        and not windows.is_absolute()
        and ".." not in posix.parts
    )


def _result(
    format_version: str | None,
    checked_files: int,
    checked_records: int,
    problems: list[str],
) -> OrganizationExportVerification:
    return OrganizationExportVerification(
        valid=not problems,
        format_version=format_version,
        checked_files=checked_files,
        checked_records=checked_records,
        problems=tuple(problems),
    )
