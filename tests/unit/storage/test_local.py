from pathlib import Path

import pytest

from signalscope.storage import local
from signalscope.storage.blob import BlobNotFoundError, BlobStorageError
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "blobs"


@pytest.fixture
def store(root: Path) -> LocalBlobStore:
    return LocalBlobStore(root)


def files_under(path: Path) -> list[str]:
    return sorted(str(file.relative_to(path)).replace("\\", "/") for file in path.rglob("*"))


async def test_put_and_get(store: LocalBlobStore, root: Path) -> None:
    await store.put("ab/abc123", b"hello")

    assert await store.get("ab/abc123") == b"hello"
    assert (root / "ab" / "abc123").read_bytes() == b"hello"


async def test_every_byte_value_survives(store: LocalBlobStore) -> None:
    data = bytes(range(256)) * 10

    await store.put("binary", data)

    assert await store.get("binary") == data


async def test_empty_blob(store: LocalBlobStore) -> None:
    await store.put("empty", b"")

    assert await store.get("empty") == b""
    assert await store.exists("empty")


async def test_exists(store: LocalBlobStore) -> None:
    assert not await store.exists("ab/abc123")

    await store.put("ab/abc123", b"x")

    assert await store.exists("ab/abc123")
    assert not await store.exists("ab")


async def test_put_replaces_existing_bytes(store: LocalBlobStore) -> None:
    await store.put("key", b"first version")
    await store.put("key", b"second")

    assert await store.get("key") == b"second"


async def test_delete(store: LocalBlobStore) -> None:
    await store.put("ab/abc123", b"x")

    await store.delete("ab/abc123")

    assert not await store.exists("ab/abc123")
    with pytest.raises(BlobNotFoundError):
        await store.get("ab/abc123")


async def test_deleting_a_missing_key_does_nothing(store: LocalBlobStore) -> None:
    await store.delete("never/stored")


async def test_missing_key(store: LocalBlobStore) -> None:
    with pytest.raises(BlobNotFoundError, match="Stored file was not found."):
        await store.get("ab/missing")


def test_creating_a_store_creates_no_folders(root: Path) -> None:
    LocalBlobStore(root)

    assert not root.exists()


async def test_folders_are_created_on_first_write(store: LocalBlobStore, root: Path) -> None:
    await store.put("a/b/c/key", b"x")

    assert files_under(root) == ["a", "a/b", "a/b/c", "a/b/c/key"]


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../outside",
        "ab/../../outside",
        "ab/./key",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "C:\\Windows\\win.ini",
        "ab\\key",
        ".hidden",
        "ab/.tmp",
        "ab//key",
        "ab/",
        "ab/key with space",
        "x" * 256,
    ],
)
async def test_unsafe_keys_are_rejected(store: LocalBlobStore, root: Path, key: str) -> None:
    for operation in [store.get(key), store.exists(key), store.delete(key)]:
        with pytest.raises(BlobStorageError, match="Blob key is not valid."):
            await operation
    with pytest.raises(BlobStorageError, match="Blob key is not valid."):
        await store.put(key, b"x")

    assert not root.parent.joinpath("outside").exists()
    assert not root.exists()


async def test_write_leaves_no_temporary_files(store: LocalBlobStore, root: Path) -> None:
    await store.put("ab/key", b"one")
    await store.put("ab/key", b"two")

    assert files_under(root) == ["ab", "ab/key"]


async def test_failed_write_keeps_the_old_bytes(
    store: LocalBlobStore, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await store.put("ab/key", b"old")

    def broken_replace(source: object, target: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(local.os, "replace", broken_replace)

    with pytest.raises(BlobStorageError, match="Could not store the file."):
        await store.put("ab/key", b"new")

    assert (root / "ab" / "key").read_bytes() == b"old"
    assert files_under(root) == ["ab", "ab/key"]
