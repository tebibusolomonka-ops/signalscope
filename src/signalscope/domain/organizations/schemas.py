import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from signalscope.domain.organizations.invitation import InvitationRole, OrganizationInvitation
from signalscope.domain.organizations.invitations import InvitationStatus, invitation_status
from signalscope.domain.organizations.membership import OrganizationRole
from signalscope.domain.organizations.model import ORGANIZATION_NAME_MAX_LENGTH, SLUG_MAX_LENGTH
from signalscope.domain.users.email import EMAIL_MAX_LENGTH


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


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, StringConstraints(min_length=1, max_length=EMAIL_MAX_LENGTH)]
    role: InvitationRole = InvitationRole.MEMBER


class InvitationRead(BaseModel):
    """An invitation without its token or token hash."""

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role: InvitationRole
    status: InvitationStatus
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    invited_by_user_id: uuid.UUID
    created_at: datetime

    @classmethod
    def build(cls, invitation: OrganizationInvitation, now: datetime) -> "InvitationRead":
        return cls(
            id=invitation.id,
            organization_id=invitation.organization_id,
            email=invitation.normalized_email,
            role=invitation.role,
            status=invitation_status(invitation, now),
            expires_at=invitation.expires_at,
            accepted_at=invitation.accepted_at,
            revoked_at=invitation.revoked_at,
            invited_by_user_id=invitation.invited_by_user_id,
            created_at=invitation.created_at,
        )


class InvitationCreated(BaseModel):
    invitation: InvitationRead
    # Shown only in this answer and never again. Share it with the invited
    # person over a secure channel; they accept it after signing in.
    invitation_token: str


class InvitationAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, StringConstraints(min_length=1, max_length=200)]
