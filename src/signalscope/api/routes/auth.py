import uuid

from fastapi import APIRouter, status

from signalscope.api.auth import AuthEnabled, Authentication, CurrentSession
from signalscope.domain.users.schemas import (
    CurrentUserRead,
    LoginRequest,
    LoginResponse,
    SessionRead,
    UserRead,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login")
async def login(request: LoginRequest, _: AuthEnabled, service: Authentication) -> LoginResponse:
    """Sign in with email and password and get a bearer token.

    The token is shown only in this answer. Any failure gives the same 401
    answer, so it never shows whether an account exists. There is no self
    registration: accounts are made with `signalscope create-user`.
    """
    new = await service.login(request.email, request.password)
    return LoginResponse(
        access_token=new.token,
        expires_at=new.expires_at,
        user=UserRead.model_validate(new.user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current: CurrentSession, service: Authentication) -> None:
    """Revoke the session of the token used for this request."""
    await service.revoke_session(current.session.id)


@router.get("/me")
async def me(current: CurrentSession) -> CurrentUserRead:
    """The signed in user and their session."""
    return CurrentUserRead(
        user=UserRead.model_validate(current.user),
        session_id=current.session.id,
        expires_at=current.session.expires_at,
    )


@router.get("/sessions")
async def list_sessions(current: CurrentSession, service: Authentication) -> list[SessionRead]:
    """The signed in user's sessions, newest first, with the current one marked."""
    found = await service.list_sessions(current.user.id)
    return [
        SessionRead(
            session_id=stored.id,
            created_at=stored.created_at,
            expires_at=stored.expires_at,
            last_seen_at=stored.last_seen_at,
            revoked=stored.revoked_at is not None,
            revoked_at=stored.revoked_at,
            current_session=stored.id == current.session.id,
        )
        for stored in found
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID, current: CurrentSession, service: Authentication
) -> None:
    """Revoke one of your sessions, for example on a lost device.

    Another user's session answers 404.
    """
    await service.revoke_user_session(current.user.id, session_id)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(current: CurrentSession, service: Authentication) -> None:
    """Revoke every session of the signed in user, including the current one."""
    await service.revoke_all_sessions(current.user.id)
