import uuid

from fastapi import APIRouter, status

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import DatabaseSession
from signalscope.domain.investigations.members import (
    CollaboratorWithUser,
    InvestigationMemberService,
)
from signalscope.domain.investigations.schemas import (
    CollaboratorCreate,
    CollaboratorRead,
    CollaboratorUpdate,
)
from signalscope.domain.organizations.schemas import MemberUserRead

router = APIRouter(prefix="/investigations", tags=["Investigations"])


@router.get("/{investigation_id}/members")
async def list_investigation_members(
    investigation_id: uuid.UUID, current: CurrentSession, session: DatabaseSession
) -> list[CollaboratorRead]:
    """The collaborators and their roles, owners first. Anyone who may view it may look."""
    service = InvestigationMemberService(session, current.user)
    return [_read(found) for found in await service.list_collaborators(investigation_id)]


@router.post("/{investigation_id}/members", status_code=status.HTTP_201_CREATED)
async def add_investigation_member(
    investigation_id: uuid.UUID,
    request: CollaboratorCreate,
    current: CurrentSession,
    session: DatabaseSession,
) -> CollaboratorRead:
    """Add a member of the investigation's organization. The role defaults to viewer.

    Needs an investigation owner, or an organization owner or admin. Works on
    closed investigations too.
    """
    added = await InvestigationMemberService(session, current.user).add(
        investigation_id, request.user_id, request.role
    )
    return _read(added)


@router.patch("/{investigation_id}/members/{user_id}")
async def change_investigation_member(
    investigation_id: uuid.UUID,
    user_id: uuid.UUID,
    request: CollaboratorUpdate,
    current: CurrentSession,
    session: DatabaseSession,
) -> CollaboratorRead:
    """Change a collaborator's role. The last owner cannot be demoted."""
    changed = await InvestigationMemberService(session, current.user).change_role(
        investigation_id, user_id, request.role
    )
    return _read(changed)


@router.delete("/{investigation_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_investigation_member(
    investigation_id: uuid.UUID,
    user_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
) -> None:
    """Remove a collaborator. The last owner cannot be removed."""
    await InvestigationMemberService(session, current.user).remove(investigation_id, user_id)


def _read(found: CollaboratorWithUser) -> CollaboratorRead:
    return CollaboratorRead(
        user=MemberUserRead.model_validate(found.user),
        role=found.collaborator.role,
        created_at=found.collaborator.created_at,
        updated_at=found.collaborator.updated_at,
    )
