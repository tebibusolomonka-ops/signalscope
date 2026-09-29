"""Helpers that make test accounts and sign them in. Test passwords only."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from password_helpers import TEST_PASSWORD, fast_hasher
from signalscope.domain.users.authentication import AuthenticationService
from signalscope.domain.users.model import User


async def create_account(
    session_factory: async_sessionmaker[AsyncSession],
    email: str,
    *,
    display_name: str | None = None,
    system_admin: bool = False,
) -> User:
    async with session_factory() as session:
        return await AuthenticationService(session, fast_hasher()).create_user(
            email,
            display_name or email.split("@")[0].capitalize(),
            TEST_PASSWORD,
            is_system_admin=system_admin,
        )


async def login(client: httpx.AsyncClient, email: str, password: str = TEST_PASSWORD) -> str:
    response = await client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
