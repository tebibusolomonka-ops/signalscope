import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.domain.investigations.collaborator import (
    CollaboratorRole,
    InvestigationCollaborator,
)
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio


async def investigation(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        created = Investigation(title="Floods")
        session.add(created)
        await session.commit()
        return created.id


async def collaborate(
    session_factory: async_sessionmaker[AsyncSession],
    investigation_id: uuid.UUID,
    user_id: uuid.UUID,
    role: CollaboratorRole,
) -> InvestigationCollaborator:
    async with session_factory() as session:
        collaborator = InvestigationCollaborator(
            investigation_id=investigation_id, user_id=user_id, role=role
        )
        session.add(collaborator)
        await session.commit()
        return collaborator


async def test_roles_and_timestamps(session_factory: async_sessionmaker[AsyncSession]) -> None:
    investigation_id = await investigation(session_factory)
    for index, role in enumerate(CollaboratorRole):
        user = await create_account(session_factory, f"user{index}@example.org")
        saved = await collaborate(session_factory, investigation_id, user.id, role)
        assert saved.created_at is not None and saved.updated_at is not None

    async with session_factory() as session:
        roles = sorted(await session.scalars(select(InvestigationCollaborator.role)))
    assert roles == sorted(CollaboratorRole)


async def test_one_role_per_user(session_factory: async_sessionmaker[AsyncSession]) -> None:
    investigation_id = await investigation(session_factory)
    user = await create_account(session_factory, "ana@example.org")
    await collaborate(session_factory, investigation_id, user.id, CollaboratorRole.VIEWER)

    with pytest.raises(IntegrityError):
        await collaborate(session_factory, investigation_id, user.id, CollaboratorRole.EDITOR)


async def test_unknown_role_is_rejected(session_factory: async_sessionmaker[AsyncSession]) -> None:
    investigation_id = await investigation(session_factory)
    user = await create_account(session_factory, "ana@example.org")

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO investigation_collaborators (investigation_id, user_id, role) "
                    "VALUES (:investigation, :user, 'admin')"
                ),
                {"investigation": investigation_id, "user": user.id},
            )


async def test_delete_behavior(session_factory: async_sessionmaker[AsyncSession]) -> None:
    investigation_id = await investigation(session_factory)
    user = await create_account(session_factory, "ana@example.org")
    await collaborate(session_factory, investigation_id, user.id, CollaboratorRole.OWNER)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(delete(User).where(User.id == user.id))
    async with session_factory() as session:
        await session.execute(delete(Investigation).where(Investigation.id == investigation_id))
        await session.commit()
        assert list(await session.scalars(select(InvestigationCollaborator))) == []
