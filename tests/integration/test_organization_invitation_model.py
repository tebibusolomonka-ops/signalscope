import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.domain.organizations.invitation import InvitationRole, OrganizationInvitation
from signalscope.domain.organizations.model import Organization
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.users.authentication import hash_token
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio

EXPIRES = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def setup(session_factory: async_sessionmaker[AsyncSession]) -> tuple[User, uuid.UUID]:
    owner = await create_account(session_factory, "owner@example.org")
    async with session_factory() as session:
        organization = await OrganizationService(session).create(owner, "Harbour", "harbour")
    return owner, organization.id


def invitation(owner: User, organization_id: uuid.UUID, **values: Any) -> OrganizationInvitation:
    fields: dict[str, Any] = {
        "organization_id": organization_id,
        "normalized_email": "ana@example.org",
        "role": InvitationRole.MEMBER,
        "token_hash": hash_token(secrets.token_urlsafe(32)),
        "expires_at": EXPIRES,
        "invited_by_user_id": owner.id,
    }
    return OrganizationInvitation(**(fields | values))


async def save(session_factory: async_sessionmaker[AsyncSession], row: object) -> None:
    async with session_factory() as session:
        session.add(row)
        await session.commit()


async def test_defaults_and_history(
    session_factory: async_sessionmaker[AsyncSession], setup: tuple[User, uuid.UUID]
) -> None:
    owner, organization_id = setup
    first = invitation(owner, organization_id, revoked_at=EXPIRES - timedelta(days=1))
    await save(session_factory, first)
    # The same address may be invited again: old rows are history.
    await save(session_factory, invitation(owner, organization_id, role=InvitationRole.ADMIN))

    assert first.created_at is not None and first.updated_at is not None
    assert first.expires_at == EXPIRES and first.accepted_at is None
    async with session_factory() as session:
        roles = sorted(await session.scalars(select(OrganizationInvitation.role)))
    assert roles == [InvitationRole.ADMIN, InvitationRole.MEMBER]


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("role", "'owner'"),
        ("token_hash", "'not-a-hash'"),
        ("normalized_email", "' '"),
        ("accepted_at", "now()"),
    ],
    ids=["owner role", "bad token hash", "blank email", "accepted and revoked"],
)
async def test_checks(
    session_factory: async_sessionmaker[AsyncSession],
    setup: tuple[User, uuid.UUID],
    column: str,
    value: str,
) -> None:
    owner, organization_id = setup
    row = invitation(owner, organization_id, revoked_at=EXPIRES)
    await save(session_factory, row)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(f"UPDATE organization_invitations SET {column} = {value} WHERE id = :id"),
                {"id": row.id},
            )


async def test_token_hash_is_unique(
    session_factory: async_sessionmaker[AsyncSession], setup: tuple[User, uuid.UUID]
) -> None:
    owner, organization_id = setup
    token_hash = hash_token("same token")
    await save(session_factory, invitation(owner, organization_id, token_hash=token_hash))

    with pytest.raises(IntegrityError):
        await save(session_factory, invitation(owner, organization_id, token_hash=token_hash))


async def test_foreign_keys(
    session_factory: async_sessionmaker[AsyncSession], setup: tuple[User, uuid.UUID]
) -> None:
    owner, organization_id = setup
    inviter = await create_account(session_factory, "inviter@example.org")
    await save(session_factory, invitation(inviter, organization_id))

    with pytest.raises(IntegrityError):
        await save(session_factory, invitation(owner, uuid.uuid4()))
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(delete(User).where(User.id == inviter.id))
    async with session_factory() as session:
        await session.execute(delete(Organization).where(Organization.id == organization_id))
        await session.commit()
        assert list(await session.scalars(select(OrganizationInvitation))) == []
