"""FastAPI dependencies for the signed in user.

The bearer token is read from the Authorization header and only ever hashed.
It is never logged or put in an error.
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from signalscope.api.dependencies import DatabaseSession
from signalscope.core.errors import ServiceUnavailableError, UnauthenticatedError
from signalscope.domain.users.authentication import AuthenticationService, ResolvedSession
from signalscope.domain.users.model import User
from signalscope.domain.users.passwords import PasswordHasher

AUTH_DISABLED = "Authentication is not enabled. Set SIGNALSCOPE_AUTH_ENABLED=true."

# auto_error is off, so a missing token gives SignalScope's own 401 answer.
bearer = HTTPBearer(auto_error=False, description="A session token from POST /auth/login.")


def auth_enabled(request: Request) -> bool:
    return bool(request.app.state.settings.auth_enabled)


def require_auth_enabled(request: Request) -> None:
    if not auth_enabled(request):
        raise ServiceUnavailableError(AUTH_DISABLED)


AuthEnabled = Annotated[None, Depends(require_auth_enabled)]


def authentication_service(request: Request, session: DatabaseSession) -> AuthenticationService:
    hasher: PasswordHasher = request.app.state.password_hasher
    return AuthenticationService(
        session, hasher, session_days=request.app.state.settings.auth_session_days
    )


Authentication = Annotated[AuthenticationService, Depends(authentication_service)]


Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


async def resolve(service: AuthenticationService, credentials: Credentials) -> ResolvedSession:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthenticatedError()
    return await service.resolve_session(credentials.credentials)


async def current_session(
    _: AuthEnabled, service: Authentication, credentials: Credentials
) -> ResolvedSession:
    """The signed in session and user. 401 without a valid token, 503 when auth is off."""
    return await resolve(service, credentials)


CurrentSession = Annotated[ResolvedSession, Depends(current_session)]


async def current_actor(
    request: Request, service: Authentication, credentials: Credentials
) -> User | None:
    """The signed in user, or None when authentication is disabled.

    For routes that stay open while authentication is disabled.
    """
    if not auth_enabled(request):
        return None
    return (await resolve(service, credentials)).user


Actor = Annotated[User | None, Depends(current_actor)]
