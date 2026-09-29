import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.domain.users.administration import UserAdministrationService
from signalscope.domain.users.schemas import AdminUserCreate, AdminUserRead, UserStatusUpdate

router = APIRouter(prefix="/admin/users", tags=["User administration"])


def administration(
    request: Request, current: CurrentSession, session: DatabaseSession
) -> UserAdministrationService:
    """The service for the signed in user. It refuses anyone but a system admin."""
    return UserAdministrationService(session, current.user, request.app.state.password_hasher)


Administration = Annotated[UserAdministrationService, Depends(administration)]


@router.get("")
async def list_users(
    service: Administration,
    page: Pagination,
    query: Annotated[str | None, Query(max_length=200)] = None,
    is_active: bool | None = None,
    is_system_admin: bool | None = None,
) -> Page[AdminUserRead]:
    """Users in the order they were made. query matches part of the email or name."""
    users, total = await service.list_users(
        query=query,
        is_active=is_active,
        is_system_admin=is_system_admin,
        limit=page.limit,
        offset=page.offset,
    )
    return Page[AdminUserRead](
        items=[AdminUserRead.model_validate(user) for user in users],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(request: AdminUserCreate, service: Administration) -> AdminUserRead:
    """Create an account with a password. There is no self registration."""
    user = await service.create_user(
        request.email,
        request.display_name,
        request.password,
        is_system_admin=request.is_system_admin,
    )
    return AdminUserRead.model_validate(user)


@router.get("/{user_id}")
async def get_user(user_id: uuid.UUID, service: Administration) -> AdminUserRead:
    return AdminUserRead.model_validate(await service.get_user(user_id))


@router.patch("/{user_id}/status")
async def change_user_status(
    user_id: uuid.UUID, request: UserStatusUpdate, service: Administration
) -> AdminUserRead:
    """Deactivate or reactivate a user.

    Deactivating revokes every session of the user at once. Reactivating does
    not bring old sessions back. The last active system admin cannot be
    deactivated (409).
    """
    if request.is_active:
        user = await service.reactivate_user(user_id)
    else:
        user = await service.deactivate_user(user_id)
    return AdminUserRead.model_validate(user)
