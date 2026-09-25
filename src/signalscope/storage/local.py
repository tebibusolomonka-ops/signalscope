import asyncio
import os
import re
import tempfile
from pathlib import Path

from signalscope.storage.blob import BlobNotFoundError, BlobStorageError

# Segments of letters, digits, dots, dashes and underscores, split by "/". A
# segment must start with a letter or digit, so "." and ".." never match, and
# neither do absolute paths, drive letters or backslashes.
KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*")
KEY_MAX_LENGTH = 255
# Unfinished writes use names that no key can have.
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"


class LocalBlobStore:
    """Keeps blobs as files under one root folder.

    The key "ab/abc123" becomes the file root/ab/abc123. Folders are created
    when the first blob is written to them. A write goes to a temporary file
    that then replaces the final file, so readers never see half a blob.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        try:
            await asyncio.to_thread(_write_atomically, path, data)
        except OSError as error:
            raise BlobStorageError("Could not store the file.") from error

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as error:
            raise BlobNotFoundError() from error
        except OSError as error:
            raise BlobStorageError("Could not read the stored file.") from error

    async def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError as error:
            raise BlobStorageError("Could not delete the stored file.") from error

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    def _path(self, key: str) -> Path:
        if len(key) > KEY_MAX_LENGTH or not KEY_PATTERN.fullmatch(key):
            raise BlobStorageError("Blob key is not valid.")
        path = self.root.joinpath(*key.split("/"))
        # The pattern already keeps keys inside the root. This also covers a
        # root that is reached through links.
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise BlobStorageError("Blob key is not valid.")
        return path


def _write_atomically(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=TEMP_PREFIX, suffix=TEMP_SUFFIX)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
