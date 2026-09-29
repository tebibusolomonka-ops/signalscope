import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import DatabaseSession
from signalscope.domain.organizations.invitations import (
    InvitationStatus,
    OrganizationInvitationService,
)
from signalscope.domain.organizations.schemas import (
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
)
from signalscope.domain.sources.scheduling import utc_now

router = APIRouter(tags=["Organization invitations"])


def invitation_service(
    request: Request, current: CurrentSession, session: DatabaseSession
) -> OrganizationInvitationService:
    return OrganizationInvitationService(
        session,
        current.user,
        invitation_days=request.app.state.settings.organization_invitation_days,
    )


Invitations = Annotated[OrganizationInvitationService, Depends(invitation_service)]


@router.post("/organizations/{organization_id}/invitations", status_code=status.HTTP_201_CREATED)
async def create_invitation(
    organization_id: uuid.UUID, request: InvitationCreate, service: Invitations
) -> InvitationCreated:
    """Invite an email address to the organization.

    There is no email sending yet: the answer holds the invitation token, once.
    Share it with the person over a secure channel. It is never shown again,
    and only its hash is stored. Owners invite admins, members and viewers;
    admins invite members and viewers.
    """
    new = await service.create_invitation(organization_id, request.email, request.role)
    return InvitationCreated(
        invitation=InvitationRead.build(new.invitation, utc_now()),
        invitation_token=new.token,
    )


@router.get("/organizations/{organization_id}/invitations")
async def list_invitations(
    organization_id: uuid.UUID, service: Invitations, status: InvitationStatus | None = None
) -> list[InvitationRead]:
    """Invitations, newest first. Tokens are never included."""
    found = await service.list_invitations(organization_id, status)
    now = utc_now()
    return [InvitationRead.build(invitation, now) for invitation in found]


@router.delete(
    "/organizations/{organization_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invitation(
    organization_id: uuid.UUID, invitation_id: uuid.UUID, service: Invitations
) -> None:
    """Revoke a pending invitation, so its token stops working."""
    await service.revoke_invitation(organization_id, invitation_id)
