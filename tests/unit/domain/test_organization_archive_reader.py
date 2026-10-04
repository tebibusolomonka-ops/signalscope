import hashlib
import io
import json
import zipfile

import pytest

from signalscope.core.errors import InvalidInputError
from signalscope.domain.organizations.archive_reader import OrganizationArchiveReader


def archive(
    *, path: str = "documents.jsonl", content: bytes = b'{"id":"one"}\n', version: str = "2"
) -> bytes:
    manifest = {
        "format_version": version,
        "record_counts": {"documents": 1},
        "files": [
            {
                "path": "documents.jsonl",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as result:
        result.writestr("manifest.json", json.dumps(manifest))
        result.writestr(path, content)
    return output.getvalue()


def test_reads_verified_sections() -> None:
    result = OrganizationArchiveReader().read(archive())

    assert result.manifest["format_version"] == "2"
    assert result.sections == {"documents": ({"id": "one"},)}
    assert result.verification.valid


def test_reads_verified_asset_content() -> None:
    content = b"asset content"
    asset_id = "11111111-1111-1111-1111-111111111111"
    document_id = "22222222-2222-2222-2222-222222222222"
    path = f"assets/{asset_id}"
    manifest = {
        "format_version": "2",
        "record_counts": {},
        "assets": [
            {
                "asset_id": asset_id,
                "document_id": document_id,
                "path": path,
                "filename": "report.pdf",
                "content_type": "application/pdf",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
        "files": [
            {
                "path": path,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as result:
        result.writestr("manifest.json", json.dumps(manifest))
        result.writestr(path, content)

    result = OrganizationArchiveReader().read(output.getvalue())

    assert result.assets == {path: content}


@pytest.mark.parametrize(
    "data",
    [
        b"not a zip file",
        archive(path="../documents.jsonl"),
        archive(content=b"not-json\n"),
        archive(version="999"),
    ],
)
def test_rejects_invalid_archives(data: bytes) -> None:
    with pytest.raises(InvalidInputError):
        OrganizationArchiveReader().read(data)


def test_rejects_oversized_member(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("signalscope.domain.organizations.archive_reader.MAX_MEMBER_BYTES", 10)

    with pytest.raises(InvalidInputError, match="too large"):
        OrganizationArchiveReader().read(archive(content=b'{"id":"long-value"}\n'))
