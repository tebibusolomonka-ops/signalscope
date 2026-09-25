import pytest

from signalscope.core.errors import SignalScopeError
from signalscope.storage.blob import BlobNotFoundError, BlobStorageError, BlobStore

pytestmark = pytest.mark.anyio


class MemoryBlobStore:
    """A fake store, to show how code uses the protocol."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        try:
            return self.blobs[key]
        except KeyError:
            raise BlobNotFoundError() from None

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs


async def copy_blob(store: BlobStore, source: str, target: str) -> None:
    await store.put(target, await store.get(source))


async def test_fake_store_follows_the_protocol() -> None:
    store = MemoryBlobStore()
    await store.put("a", b"\x00\x01 data")

    await copy_blob(store, "a", "b")

    assert await store.get("b") == b"\x00\x01 data"
    assert await store.exists("b")


async def test_missing_blob() -> None:
    store: BlobStore = MemoryBlobStore()

    assert not await store.exists("missing")
    with pytest.raises(BlobNotFoundError, match="Stored file was not found."):
        await store.get("missing")
    await store.delete("missing")


def test_errors() -> None:
    assert issubclass(BlobNotFoundError, BlobStorageError)
    assert issubclass(BlobStorageError, SignalScopeError)
    assert str(BlobStorageError()) == "File storage failed."
