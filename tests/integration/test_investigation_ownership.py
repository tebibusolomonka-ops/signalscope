import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.investigations.service import InvestigationService
from signalscope.domain.organizations.model import Organization
from signalscope.domain.organizations.service import OrganizationService

pytestmark = pytest.mark.anyio


async def test_existing_workflow_leaves_legacy_nulls(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        investigation = await InvestigationService(session).create("Floods")

    async with session_factory() as session:
        stored = await session.get(Investigation, investigation.id)
    assert stored is not None
    assert (stored.organization_id, stored.created_by_user_id) == (None, None)


async def test_owned_investigation(session_factory: async_sessionmaker[AsyncSession]) -> None:
    user = await create_account(session_factory, "ana@example.org")
    async with session_factory() as session:
        organization = await OrganizationService(session).create(user, "News", "news")
        investigation = Investigation(
            title="Floods", organization_id=organization.id, created_by_user_id=user.id
        )
        session.add(investigation)
        await session.commit()

    async with session_factory() as session:
        stored = await session.get(Investigation, investigation.id)
        assert stored is not None
        assert (stored.organization_id, stored.created_by_user_id) == (organization.id, user.id)
        # An organization or creator with investigations cannot be deleted.
        with pytest.raises(IntegrityError):
            await session.execute(delete(Organization).where(Organization.id == organization.id))


@pytest.mark.parametrize("field", ["organization_id", "created_by_user_id"])
async def test_references_must_exist(
    session_factory: async_sessionmaker[AsyncSession], field: str
) -> None:
    async with session_factory() as session:
        session.add(Investigation(title="Floods", **{field: uuid.uuid4()}))
        with pytest.raises(IntegrityError):
            await session.commit()
