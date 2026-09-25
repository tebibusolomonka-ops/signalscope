import uuid
from dataclasses import dataclass
from enum import StrEnum

from signalscope.domain.documents.model import Document
from signalscope.domain.documents.repository import DocumentRepository


class DuplicateReason(StrEnum):
    EXTERNAL_ID = "external_id"
    URL = "url"
    CONTENT = "content"


@dataclass(frozen=True, slots=True)
class Duplicate:
    reason: DuplicateReason
    document: Document


async def find_duplicate(
    documents: DocumentRepository,
    source_id: uuid.UUID,
    *,
    external_id: str | None,
    url: str | None,
    content_hash: str | None,
) -> Duplicate | None:
    """Find a document of the same source that a new item repeats.

    The most stable identifier is checked first: external ID, then URL, then
    the content fingerprint. Missing values are skipped. Nothing is changed.
    """
    if external_id is not None:
        document = await documents.find_by_external_id(source_id, external_id)
        if document is not None:
            return Duplicate(DuplicateReason.EXTERNAL_ID, document)
    if url is not None:
        document = await documents.find_by_url(source_id, url)
        if document is not None:
            return Duplicate(DuplicateReason.URL, document)
    if content_hash is not None:
        document = await documents.find_by_content_hash(source_id, content_hash)
        if document is not None:
            return Duplicate(DuplicateReason.CONTENT, document)
    return None
