import io
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from password_helpers import OTHER_PASSWORD, TEST_PASSWORD, fast_hasher
from signalscope.cli import create_user
from signalscope.core.settings import Settings
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings) -> Settings:
    # Auth is off: the bootstrap command works either way.
    return Settings(database_url=migrated_database.database_url, auth_enabled=False)


class Prompts:
    """Stands in for getpass. Records the prompts and gives back set answers."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0)


async def run(settings: Settings, email: str, **options: Any) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await create_user(settings, email, out, err, hasher=fast_hasher(), **options)
    return code, out.getvalue(), err.getvalue()


async def users(session_factory: async_sessionmaker[AsyncSession]) -> list[User]:
    async with session_factory() as session:
        return list(await session.scalars(select(User)))


async def test_interactive_password(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    prompts = Prompts(TEST_PASSWORD, TEST_PASSWORD)

    code, out, err = await run(settings, "Ana@Example.org", ask_password=prompts)

    assert (code, err) == (0, "")
    [user] = await users(session_factory)
    assert out == f"User ID: {user.id}\nEmail: Ana@Example.org\nSystem admin: no\n"
    assert prompts.prompts == ["Password: ", "Repeat password: "]
    assert user.display_name == "Ana"
    assert TEST_PASSWORD not in out + err
    async with session_factory() as session:
        credential = await session.get(UserPasswordCredential, user.id)
    assert credential is not None and credential.password_hash not in out


async def test_passwords_must_match(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    code, out, err = await run(
        settings, "ana@example.org", ask_password=Prompts(TEST_PASSWORD, OTHER_PASSWORD)
    )

    assert (code, out) == (1, "")
    assert err == "Error: The passwords do not match.\n"
    assert await users(session_factory) == []


async def test_password_from_standard_input(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    stdin = io.StringIO(f"{TEST_PASSWORD}\nignored second line\n")

    code, out, _ = await run(
        settings,
        "admin@example.org",
        display_name="Admin",
        system_admin=True,
        password_stdin=True,
        stdin=stdin,
    )

    assert code == 0
    assert out.endswith("System admin: yes\n")
    [user] = await users(session_factory)
    assert (user.display_name, user.is_system_admin) == ("Admin", True)


@pytest.mark.parametrize(
    ("email", "password", "message"),
    [
        ("not an email", TEST_PASSWORD, "Email address is not valid."),
        ("ana@example.org", "short", "Password must be from 12 to 1024 characters."),
    ],
    ids=["bad email", "short password"],
)
async def test_bad_input(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    email: str,
    password: str,
    message: str,
) -> None:
    code, out, err = await run(settings, email, password_stdin=True, stdin=io.StringIO(password))

    assert (code, out, err) == (1, "", f"Error: {message}\n")
    assert await users(session_factory) == []


async def test_duplicate_user(settings: Settings) -> None:
    await run(settings, "ana@example.org", password_stdin=True, stdin=io.StringIO(TEST_PASSWORD))

    code, _, err = await run(
        settings, "ANA@example.org", password_stdin=True, stdin=io.StringIO(TEST_PASSWORD)
    )

    assert code == 1
    assert err == "Error: An account with this email already exists.\n"
