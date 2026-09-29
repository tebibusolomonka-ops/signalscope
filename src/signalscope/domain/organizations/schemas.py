import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from signalscope.domain.organizations.membership import OrganizationRole
from signalscope.domain.organizations.model import ORGANIZATION_NAME_MAX_LENGTH, SLUG_MAX_LENGTH


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=ORGANIZATION_NAME_MAX_LENGTH
        ),
    ]
    # Lowercase letters, digits and single hyphens, such as "harbour-watch".
    slug: Annotated[str, StringConstraints(min_length=1, max_length=SLUG_MAX_LENGTH + 10)]


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class MyOrganizationRead(BaseModel):
    organization: OrganizationRead
    # The signed in user's role in it.
    role: OrganizationRole


class MemberUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str


class OrganizationMemberRead(BaseModel):
    user: MemberUserRead
    role: OrganizationRole
    created_at: datetime
    updated_at: datetime


class OrganizationMemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    role: OrganizationRole = OrganizationRole.MEMBER


class OrganizationMemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: OrganizationRole
