import hashlib
import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from signalscope.core.errors import InvalidInputError
from signalscope.domain.documents.asset import (
    CONTENT_TYPE_MAX_LENGTH,
    FILENAME_MAX_LENGTH,
    DocumentAsset,
)
from signalscope.storage.blob import BlobStorageError, BlobStore

logger = logging.getLogger(__name__)

# The same limit as the PDF and DOCX parsers.
MAX_FILE_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RawFile:
    """A file that passed the checks and is ready to be stored."""

    filename: str | None
    content_type: str
    data: bytes
    sha256: str

    def to_asset(self, document_id: uuid.UUID, storage_key: str) -> DocumentAsset:
        return DocumentAsset(
            document_id=document_id,
            storage_key=storage_key,
            filename=self.filename,
            content_type=self.content_type,
            size_bytes=len(self.data),
            sha256=self.sha256,
        )


def prepare_file(filename: str | None, content_type: str, data: bytes) -> RawFile:
    content_type = content_type.strip()
    if not content_type:
        raise InvalidInputError("Content type must not be empty.")
    if len(content_type) > CONTENT_TYPE_MAX_LENGTH:
        raise InvalidInputError(
            f"Content type must be at most {CONTENT_TYPE_MAX_LENGTH} characters."
        )
    if len(data) > MAX_FILE_BYTES:
        raise InvalidInputError(f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    return RawFile(
        filename=clean_filename(filename),
        content_type=content_type,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def clean_filename(filename: str | None) -> str | None:
    """Keep only the file name, without any folders a client sent."""
    if filename is None:
        return None
    name = re.split(r"[\\/]", filename)[-1].strip()
    return name[:FILENAME_MAX_LENGTH] or None


def new_blob_key() -> str:
    """A new random key. User file names never become keys."""
    value = uuid.uuid4().hex
    # The first two characters spread the files over at most 256 folders.
    return f"{value[:2]}/{value}"


@asynccontextmanager
async def stored_blob(blobs: BlobStore, data: bytes) -> AsyncIterator[str]:
    """Store data under a new key and yield the key.

    When the block fails, for example because the database rejected the row
    that points to the blob, the blob is deleted again.
    """
    key = new_blob_key()
    await blobs.put(key, data)
    try:
        yield key
    except BaseException:
        try:
            await blobs.delete(key)
        except BlobStorageError:
            # The original error matters more. The file is left for a later cleanup.
            logger.exception("Could not delete blob %s after a failed save", key)
        raise
