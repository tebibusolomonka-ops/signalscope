import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints

from signalscope.domain.documents.model import EXTERNAL_ID_MAX_LENGTH, LANGUAGE_MAX_LENGTH

ExternalId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=EXTERNAL_ID_MAX_LENGTH)
]
Language = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=LANGUAGE_MAX_LENGTH)
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
    published_at: AwareDatetime | None = None


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
