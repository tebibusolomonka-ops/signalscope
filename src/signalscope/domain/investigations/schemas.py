import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

from signalscope.domain.investigations.item import ITEM_LABEL_MAX_LENGTH, InvestigationItemType
from signalscope.domain.investigations.model import (
    INVESTIGATION_TITLE_MAX_LENGTH,
    InvestigationStatus,
)

Title = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=INVESTIGATION_TITLE_MAX_LENGTH
    ),
]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class InvestigationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    description: Description | None = None


class InvestigationUpdate(BaseModel):
    """Only the fields that are sent change. description: null clears it.

    A closed investigation can only change its status; send "status": "open"
    to reopen it, with other changes in the same request if needed.
    """

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    description: Description | None = None
    status: InvestigationStatus | None = None


class InvestigationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    status: InvestigationStatus
    created_at: datetime
    updated_at: datetime


class InvestigationItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: InvestigationItemType
    reference_id: uuid.UUID
    label: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True, min_length=1, max_length=ITEM_LABEL_MAX_LENGTH
            ),
        ]
        | None
    ) = None


class InvestigationItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_type: InvestigationItemType
    reference_id: uuid.UUID
    label: str | None
    # What the record looked like when it was saved. It is never updated.
    snapshot: dict[str, Any]
    created_at: datetime
