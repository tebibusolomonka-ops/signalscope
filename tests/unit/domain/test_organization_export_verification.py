import hashlib
import io
import json
import zipfile
from uuid import UUID

import pytest

from signalscope.domain.organizations.export_verification import (
    OrganizationExportVerificationService,
)


def archive(
    *,
    content: bytes = b'{"id":"1"}\n',
    path: str = "documents.jsonl",
    count: int = 1,
    include_member: bool = True,
    manifest_path: str | None = None,
    assets: list[dict[str, object]] | None = None,
) -> bytes:
    listed_path = manifest_path or path
    manifest = {
        "format_version": "2",
        "record_counts": {"documents": count},
        "assets": assets or [],
        "files": [
            {
                "path": listed_path,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as result:
        result.writestr("manifest.json", json.dumps(manifest))
        if include_member:
            result.writestr(path, content)
    return output.getvalue()


def test_verifies_valid_archive() -> None:
    result = OrganizationExportVerificationService().verify(archive())

    assert result.valid
    assert result.format_version == "2"
    assert result.checked_files == 1
    assert result.checked_records == 1
    assert result.problems == ()


def test_rejects_changed_member() -> None:
    data = archive(content=b'{"id":"1"}\n')
    source = zipfile.ZipFile(io.BytesIO(data))
    output = io.BytesIO()
    with source, zipfile.ZipFile(output, "w") as changed:
        changed.writestr("manifest.json", source.read("manifest.json"))
        changed.writestr("documents.jsonl", b'{"id":"2"}\n')

    result = OrganizationExportVerificationService().verify(output.getvalue())

    assert not result.valid
    assert any("checksum" in problem for problem in result.problems)


def test_rejects_missing_member() -> None:
    result = OrganizationExportVerificationService().verify(archive(include_member=False))

    assert not result.valid
    assert "Archive member is missing: documents.jsonl" in result.problems


def test_rejects_bad_jsonl() -> None:
    result = OrganizationExportVerificationService().verify(archive(content=b"not-json\n"))

    assert not result.valid
    assert "Archive member is not readable JSON: documents.jsonl" in result.problems


def test_rejects_path_traversal() -> None:
    result = OrganizationExportVerificationService().verify(
        archive(path="../documents.jsonl", manifest_path="documents.jsonl")
    )

    assert not result.valid
    assert "Unsafe archive path: ../documents.jsonl" in result.problems


def test_rejects_duplicate_archive_path() -> None:
    data = archive()
    source = zipfile.ZipFile(io.BytesIO(data))
    output = io.BytesIO()
    with source, zipfile.ZipFile(output, "w") as duplicate:
        duplicate.writestr("manifest.json", source.read("manifest.json"))
        duplicate.writestr("documents.jsonl", b'{"id":"1"}\n')
        with pytest.warns(UserWarning, match="Duplicate name"):
            duplicate.writestr("documents.jsonl", b'{"id":"1"}\n')

    result = OrganizationExportVerificationService().verify(output.getvalue())

    assert not result.valid
    assert "Duplicate archive path: documents.jsonl" in result.problems


def test_rejects_wrong_record_count() -> None:
    result = OrganizationExportVerificationService().verify(archive(count=2))

    assert not result.valid
    assert "Record count does not match: documents.jsonl" in result.problems


def test_verifies_binary_asset_metadata_and_content() -> None:
    asset_id = UUID("11111111-1111-1111-1111-111111111111")
    document_id = UUID("22222222-2222-2222-2222-222222222222")
    content = b"binary content"
    path = f"assets/{asset_id}"
    asset = {
        "asset_id": str(asset_id),
        "document_id": str(document_id),
        "path": path,
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }

    result = OrganizationExportVerificationService().verify(
        archive(content=content, path=path, count=0, assets=[asset])
    )

    assert result.valid
    assert result.checked_files == 1
    assert result.checked_records == 0


def test_rejects_asset_manifest_metadata_that_differs_from_file_entry() -> None:
    asset_id = "11111111-1111-1111-1111-111111111111"
    content = b"binary content"
    path = f"assets/{asset_id}"
    asset = {
        "asset_id": asset_id,
        "document_id": "22222222-2222-2222-2222-222222222222",
        "path": path,
        "filename": None,
        "content_type": "application/octet-stream",
        "size_bytes": len(content) + 1,
        "sha256": hashlib.sha256(content).hexdigest(),
    }

    result = OrganizationExportVerificationService().verify(
        archive(content=content, path=path, count=0, assets=[asset])
    )

    assert not result.valid
    assert f"Manifest asset metadata does not match its file entry: {path}" in result.problems


def test_rejects_asset_path_that_does_not_match_its_id() -> None:
    asset = {
        "asset_id": "11111111-1111-1111-1111-111111111111",
        "document_id": "22222222-2222-2222-2222-222222222222",
        "path": "assets/different",
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1,
        "sha256": hashlib.sha256(b"x").hexdigest(),
    }

    result = OrganizationExportVerificationService().verify(
        archive(content=b"x", path="assets/different", count=0, assets=[asset])
    )

    assert not result.valid
    assert "Manifest asset path is invalid." in result.problems
