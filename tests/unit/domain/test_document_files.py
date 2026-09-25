import hashlib
import re
import uuid

import pytest

from signalscope.core.errors import InvalidInputError
from signalscope.domain.documents import files
from signalscope.domain.documents.files import (
    clean_filename,
    new_blob_key,
    prepare_file,
    stored_blob,
)
from signalscope.storage.blob import BlobStorageError


class MemoryBlobStore:
    def __init__(self, fail_delete: bool = False) -> None:
        self.blobs: dict[str, bytes] = {}
        self.fail_delete = fail_delete

    async def put(self, key: str, data: bytes) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        if self.fail_delete:
            raise BlobStorageError("Could not delete the stored file.")
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs


def test_prepare_file() -> None:
    file = prepare_file("C:\\Users\\jane\\report.pdf", " application/pdf ", b"%PDF data")

    assert file.filename == "report.pdf"
    assert file.content_type == "application/pdf"
    assert file.sha256 == hashlib.sha256(b"%PDF data").hexdigest()


def test_file_becomes_an_asset() -> None:
    document_id = uuid.uuid4()

    asset = prepare_file("a.txt", "text/plain", b"hello").to_asset(document_id, "ab/key")

    assert (asset.document_id, asset.storage_key, asset.filename) == (
        document_id,
        "ab/key",
        "a.txt",
    )
    assert (asset.content_type, asset.size_bytes) == ("text/plain", 5)
    assert asset.sha256 == hashlib.sha256(b"hello").hexdigest()


@pytest.mark.parametrize("content_type", ["", "   ", "x" * 256])
def test_bad_content_type_is_rejected(content_type: str) -> None:
    with pytest.raises(InvalidInputError, match="Content type"):
        prepare_file("a.txt", content_type, b"x")


def test_large_file_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(files, "MAX_FILE_BYTES", 4)

    prepare_file("a.txt", "text/plain", b"1234")
    with pytest.raises(InvalidInputError, match="File is larger than 0 MB."):
        prepare_file("a.txt", "text/plain", b"12345")


def test_default_size_limit_is_fifty_megabytes() -> None:
    assert files.MAX_FILE_BYTES == 50 * 1024 * 1024


@pytest.mark.parametrize(
    ("filename", "cleaned"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\jane\\notes.txt", "notes.txt"),
        ("  spaced name.docx  ", "spaced name.docx"),
        ("folder/", None),
        ("", None),
        (None, None),
        ("x" * 300 + ".txt", "x" * 255),
    ],
)
def test_clean_filename(filename: str | None, cleaned: str | None) -> None:
    assert clean_filename(filename) == cleaned


def test_blob_keys_are_random_and_spread_over_folders() -> None:
    first, second = new_blob_key(), new_blob_key()

    assert first != second
    assert re.fullmatch(r"[0-9a-f]{2}/[0-9a-f]{32}", first)
    assert first[3:5] == first[:2]


@pytest.mark.anyio
async def test_stored_blob_keeps_the_blob_when_the_block_succeeds() -> None:
    store = MemoryBlobStore()

    async with stored_blob(store, b"data") as key:
        pass

    assert store.blobs == {key: b"data"}


@pytest.mark.anyio
async def test_stored_blob_is_deleted_when_the_block_fails() -> None:
    store = MemoryBlobStore()

    with pytest.raises(RuntimeError, match="database is down"):
        async with stored_blob(store, b"data"):
            raise RuntimeError("database is down")

    assert store.blobs == {}


@pytest.mark.anyio
async def test_failed_cleanup_does_not_hide_the_original_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = MemoryBlobStore(fail_delete=True)

    with pytest.raises(RuntimeError, match="database is down"):
        async with stored_blob(store, b"data"):
            raise RuntimeError("database is down")

    assert "after a failed save" in caplog.text
