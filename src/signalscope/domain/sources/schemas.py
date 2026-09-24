import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from signalscope.domain.sources.model import SOURCE_NAME_MAX_LENGTH, SourceType

URL_MAX_LENGTH = 2048
TYPES_THAT_NEED_URL = frozenset({SourceType.WEB, SourceType.RSS})


class SourceCreate(BaseModel):
    # Unknown fields such as id or created_at are rejected instead of ignored.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: SourceType
    name: str = Field(min_length=1, max_length=SOURCE_NAME_MAX_LENGTH)
    url: str | None = Field(default=None, min_length=1, max_length=URL_MAX_LENGTH)

    @model_validator(mode="after")
    def check_url(self) -> Self:
        if self.url is None and self.type in TYPES_THAT_NEED_URL:
            raise ValueError(f"url is required for {self.type} sources")
        return self


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: SourceType
    name: str
    url: str | None
    created_at: datetime
    updated_at: datetime
