import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, StringConstraints

from signalscope.domain.documents.language import normalize_language
from signalscope.domain.documents.model import (
    EXTERNAL_ID_MAX_LENGTH,
    LANGUAGE_MAX_LENGTH,
    URL_MAX_LENGTH,
    url_fits,
)
from signalscope.domain.documents.revision import DocumentRevision

# Converted to UTC, so responses look the same before and after a database round trip.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]

ExternalId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=EXTERNAL_ID_MAX_LENGTH)
]
Language = Annotated[
    str, StringConstraints(max_length=LANGUAGE_MAX_LENGTH), AfterValidator(normalize_language)
]


def _check_url_size(url: str) -> str:
    if not url_fits(url):
        raise ValueError(f"url must be at most {URL_MAX_LENGTH} bytes")
    return url


Url = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1), AfterValidator(_check_url_size)
]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DocumentCreate(BaseModel):
    # Unknown fields such as id or created_at are rejected instead of ignored.
    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID
    external_id: ExternalId | None = None
    url: Url | None = None
    title: Title | None = None
    # Content is stored exactly as sent.
    content: str | None = None
    language: Language | None = None
    published_at: UtcDatetime | None = None


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    external_id: str | None
    url: str | None
    title: str | None
    content: str | None
    language: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentRevisionSummary(BaseModel):
    """One earlier state of a document, without its text."""

    version: int
    title: str | None
    language: str | None
    url: str | None
    content_hash: str | None
    # Number of characters in the stored content, or None when there was none.
    content_length: int | None
    created_at: datetime

    @classmethod
    def from_revision(cls, revision: DocumentRevision) -> "DocumentRevisionSummary":
        return cls(
            version=revision.version,
            title=revision.title,
            language=revision.language,
            url=revision.url,
            content_hash=revision.content_hash,
            content_length=None if revision.content is None else len(revision.content),
            created_at=revision.created_at,
        )


class DocumentRevisionList(BaseModel):
    items: list[DocumentRevisionSummary]


class DocumentRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    version: int
    title: str | None
    content: str | None
    language: str | None
    url: str | None
    content_hash: str | None
    # What the parser reported for this state, such as a page count.
    parser_metadata: dict[str, Any]
    created_at: datetime
