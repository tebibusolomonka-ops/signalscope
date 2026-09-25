import uuid
from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, StringConstraints

from signalscope.domain.documents.language import normalize_language
from signalscope.domain.documents.model import EXTERNAL_ID_MAX_LENGTH, LANGUAGE_MAX_LENGTH

# Converted to UTC, so responses look the same before and after a database round trip.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]

ExternalId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=EXTERNAL_ID_MAX_LENGTH)
]
Language = Annotated[
    str, StringConstraints(max_length=LANGUAGE_MAX_LENGTH), AfterValidator(normalize_language)
]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DocumentCreate(BaseModel):
    # Unknown fields such as id or created_at are rejected instead of ignored.
    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID
    external_id: ExternalId | None = None
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
    title: str | None
    content: str | None
    language: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
