from fastapi import APIRouter, status

from signalscope.api.auth import AuthEnabled, Authentication, CurrentSession
from signalscope.domain.users.schemas import (
    CurrentUserRead,
    LoginRequest,
    LoginResponse,
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
