from typing import Protocol

from signalscope.core.errors import SignalScopeError


class BlobStorageError(SignalScopeError):
    default_message = "File storage failed."


class BlobNotFoundError(BlobStorageError):
    default_message = "Stored file was not found."


class BlobStore(Protocol):
    """Stores raw file bytes under keys.

    Keys are opaque strings. Each store decides how a key maps to a file or an
    object, and which keys it accepts.
    """

    async def put(self, key: str, data: bytes) -> None:
        """Store data under key, replacing anything already stored there."""
        ...

    async def get(self, key: str) -> bytes:
        """Return the stored bytes. Raises BlobNotFoundError when nothing is stored."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the stored bytes. Deleting a key that is not stored does nothing."""
        ...

    async def exists(self, key: str) -> bool: ...
