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
