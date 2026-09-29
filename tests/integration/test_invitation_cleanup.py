import io
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.cli import cleanup_organization_invitations
from signalscope.core.settings import Settings
from signalscope.domain.organizations.invitation import InvitationRole, OrganizationInvitation
from signalscope.domain.organizations.invitation_cleanup import InvitationCleanupService
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.users.authentication import hash_token

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
Times = tuple[datetime, datetime | None, datetime | None]


def at(days: float) -> datetime:
    return NOW + timedelta(days=days)


async def add_invitations(
    session_factory: async_sessionmaker[AsyncSession], rows: dict[str, Times]
) -> dict[str, uuid.UUID]:
    """One invitation per name, with its expiry, accepted and revoked times."""
    owner = await create_account(session_factory, "owner@example.org")
    async with session_factory() as session:
        organization = await OrganizationService(session).create(owner, "Harbour", "harbour")
    ids = {}
    async with session_factory() as session:
        for index, (name, (expires_at, accepted_at, revoked_at)) in enumerate(rows.items()):
            row = OrganizationInvitation(
                organization_id=organization.id,
                normalized_email=f"person{index}@example.org",
                role=InvitationRole.MEMBER,
                token_hash=hash_token(secrets.token_urlsafe(32)),
                expires_at=expires_at,
                accepted_at=accepted_at,
                revoked_at=revoked_at,
                invited_by_user_id=owner.id,
            )
            session.add(row)
            await session.flush()
            ids[name] = row.id
        await session.commit()
    return ids


async def remaining(
    session_factory: async_sessionmaker[AsyncSession], ids: dict[str, uuid.UUID]
) -> set[str]:
    async with session_factory() as session:
        found = set(await session.scalars(select(OrganizationInvitation.id)))
    return {name for name, row_id in ids.items() if row_id in found}


async def test_only_old_finished_invitations_are_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await add_invitations(
        session_factory,
        {
            "pending": (at(3), None, None),
            "recently accepted": (at(3), at(-1), None),
            "old accepted": (at(-30), at(-40), None),
            "recently revoked": (at(3), None, at(-2)),
            "old revoked": (at(-20), None, at(-31)),
            "recently expired": (at(-5), None, None),
            "old expired": (at(-45), None, None),
        },
    )

    async with session_factory() as session:
        result = await InvitationCleanupService(session, lambda: NOW).run(30, 100)

    assert (result.checked, result.deleted) == (3, 3)
    assert await remaining(session_factory, ids) == {
        "pending",
        "recently accepted",
        "recently revoked",
        "recently expired",
    }


async def test_limit(session_factory: async_sessionmaker[AsyncSession]) -> None:
    ids = await add_invitations(
        session_factory, {f"old {index}": (at(-40 - index), None, None) for index in range(5)}
    )

    deleted = []
    for limit in (2, 10, 10):
        async with session_factory() as session:
            result = await InvitationCleanupService(session, lambda: NOW).run(30, limit)
        deleted.append(result.deleted)

    assert deleted == [2, 3, 0]
    assert await remaining(session_factory, ids) == set()


async def test_command(
    database_engine: AsyncEngine,
    migrated_database: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await add_invitations(
        session_factory, {"pending": (at(3), None, None), "old": (at(-5), None, None)}
    )
    settings = Settings(
        database_url=migrated_database.database_url, organization_invitation_retention_days=2
    )
    out, err = io.StringIO(), io.StringIO()

    code = await cleanup_organization_invitations(10, settings, out, err, clock=lambda: NOW)

    assert (code, out.getvalue(), err.getvalue()) == (0, "Checked: 1\nDeleted: 1\n", "")
    assert "@" not in out.getvalue()
    assert await remaining(session_factory, ids) == {"pending"}
