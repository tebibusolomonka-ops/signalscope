import uuid

from fastapi import APIRouter, status

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import DatabaseSession
from signalscope.domain.organizations.access_summary import OrganizationAccessSummaryService
from signalscope.domain.organizations.membership import OrganizationMembership
from signalscope.domain.organizations.schemas import (
    CollaboratorCounts,
    InvestigationCounts,
    InvitationCounts,
    MemberCounts,
    MemberStatusCounts,
    MemberUserRead,
    MyOrganizationRead,
    OrganizationAccessSummaryRead,
    OrganizationCreate,
    OrganizationMemberCreate,
    OrganizationMemberRead,
    OrganizationMemberUpdate,
    OrganizationRead,
)
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.users.model import User

router = APIRouter(prefix="/organizations", tags=["Organizations"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_organization(
    request: OrganizationCreate, current: CurrentSession, session: DatabaseSession
) -> OrganizationRead:
    """Create an organization. The signed in user becomes its owner."""
    organization = await OrganizationService(session).create(
        current.user, request.name, request.slug
    )
    return OrganizationRead.model_validate(organization)


@router.get("")
async def list_organizations(
    current: CurrentSession, session: DatabaseSession
) -> list[MyOrganizationRead]:
    """The organizations the signed in user belongs to, with their role."""
    found = await OrganizationService(session).list_for_user(current.user)
    return [
        MyOrganizationRead(organization=OrganizationRead.model_validate(organization), role=role)
        for organization, role in found
    ]


@router.get("/{organization_id}")
async def get_organization(
    organization_id: uuid.UUID, current: CurrentSession, session: DatabaseSession
) -> OrganizationRead:
    """An organization the user belongs to. Others answer 404."""
    organization = await OrganizationService(session).get(current.user, organization_id)
    return OrganizationRead.model_validate(organization)


@router.get("/{organization_id}/members")
async def list_organization_members(
    organization_id: uuid.UUID, current: CurrentSession, session: DatabaseSession
) -> list[OrganizationMemberRead]:
    """Every member and their role, owners first. Any member may look."""
    members = await OrganizationService(session).list_members(current.user, organization_id)
    return [_member_read(member.membership, member.user) for member in members]


@router.post("/{organization_id}/members", status_code=status.HTTP_201_CREATED)
async def add_organization_member(
    organization_id: uuid.UUID,
    request: OrganizationMemberCreate,
    current: CurrentSession,
    session: DatabaseSession,
) -> OrganizationMemberRead:
    """Add an active user by ID. Owners add any role; admins add members and viewers."""
    service = OrganizationService(session)
    membership = await service.add_member(
        current.user, organization_id, request.user_id, request.role
    )
    return await _read(session, membership)


@router.patch("/{organization_id}/members/{user_id}")
async def change_organization_member(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    request: OrganizationMemberUpdate,
    current: CurrentSession,
    session: DatabaseSession,
) -> OrganizationMemberRead:
    """Change a member's role. The last owner cannot be demoted."""
    membership = await OrganizationService(session).change_member_role(
        current.user, organization_id, user_id, request.role
    )
    return await _read(session, membership)


@router.delete("/{organization_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_organization_member(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
) -> None:
    """Remove a member. The last owner cannot be removed."""
    await OrganizationService(session).remove_member(current.user, organization_id, user_id)


@router.get("/{organization_id}/access-summary")
async def get_access_summary(
    organization_id: uuid.UUID, current: CurrentSession, session: DatabaseSession
) -> OrganizationAccessSummaryRead:
    """Counts of members, invitations, investigations and collaborators.

    For organization owners and admins, and system admins. Other members get
    403 and non-members 404.
    """
    found = await OrganizationAccessSummaryService(session, current.user).summary(organization_id)
    return OrganizationAccessSummaryRead(
        organization=OrganizationRead.model_validate(found.organization),
        members=MemberCounts(
            total=found.total_members, **{role.value: n for role, n in found.members.items()}
        ),
        member_status=MemberStatusCounts(
            active=found.active_members, inactive=found.inactive_members
        ),
        invitations=InvitationCounts(
            **{status.value: n for status, n in found.invitations.items()}
        ),
        investigations=InvestigationCounts(
            **{status.value: n for status, n in found.investigations.items()}
        ),
        collaborators=CollaboratorCounts(
            **{role.value: n for role, n in found.collaborators.items()}
        ),
    )


async def _read(
    session: DatabaseSession, membership: OrganizationMembership
) -> OrganizationMemberRead:
    user = await session.get(User, membership.user_id)
    assert user is not None
    return _member_read(membership, user)


def _member_read(membership: OrganizationMembership, user: User) -> OrganizationMemberRead:
    return OrganizationMemberRead(
        user=MemberUserRead.model_validate(user),
        role=membership.role,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )
