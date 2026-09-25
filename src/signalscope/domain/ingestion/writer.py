import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.fingerprint import content_fingerprint
from signalscope.domain.documents.model import (
    EXTERNAL_ID_MAX_LENGTH,
    LANGUAGE_MAX_LENGTH,
    URL_MAX_LENGTH,
    Document,
)
from signalscope.domain.documents.repository import DocumentRepository
from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.duplicates import DuplicateReason, find_duplicate


class WriteOutcome(StrEnum):
    CREATED = "created"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class WriteResult:
    outcome: WriteOutcome
    # The new document, or the existing one the item repeats.
    document: Document
    duplicate_reason: DuplicateReason | None = None


class DocumentWriter:
    """Saves ingested items as documents of a source.

    It uses the caller's session and never commits, so the caller decides how
    items are grouped into transactions. Existing documents are never changed.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.documents = DocumentRepository(session)

    async def write(self, source_id: uuid.UUID, item: IngestedItem) -> WriteResult:
        external_id = _fit(item.external_id, EXTERNAL_ID_MAX_LENGTH)
        url = _fit(item.url, URL_MAX_LENGTH)
        title = _text(item.title)
        content = item.content if _text(item.content) else None
        content_hash = content_fingerprint(title=title, content=content, url=url)

        duplicate = await find_duplicate(
            self.documents,
            source_id,
            external_id=external_id,
            url=url,
            content_hash=content_hash,
        )
        if duplicate is not None:
            return WriteResult(WriteOutcome.DUPLICATE, duplicate.document, duplicate.reason)

        document = Document(
            source_id=source_id,
            external_id=external_id,
            url=url,
            title=title,
            content=content,
            language=_fit(item.language, LANGUAGE_MAX_LENGTH),
            published_at=item.published_at,
            content_hash=content_hash,
        )
        await self.documents.add(document)
        return WriteResult(WriteOutcome.CREATED, document)


def _fit(value: str | None, max_length: int) -> str | None:
    # Too long values are dropped, not cut, because a cut ID or URL points elsewhere.
    return value if value is not None and len(value) <= max_length else None


def _text(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None
