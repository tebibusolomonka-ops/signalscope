import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.organizations.drill_record import (
    DisasterRecoveryDrillMode,
    DisasterRecoveryDrillStatus,
    OrganizationDisasterRecoveryDrill,
)
from signalscope.domain.organizations.model import Organization
from signalscope.domain.users.model import User
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def drill_for(tenants: Tenants, **values: Any) -> OrganizationDisasterRecoveryDrill:
    fields: dict[str, Any] = {
        "organization_id": tenants.a.id,
        "requested_by_user_id": tenants.a.owner_id,
        "mode": DisasterRecoveryDrillMode.VERIFICATION_ONLY,
        "status": DisasterRecoveryDrillStatus.PENDING,
        "started_at": NOW,
    }
    return OrganizationDisasterRecoveryDrill(**(fields | values))


async def save(
    session_factory: async_sessionmaker[AsyncSession],
    drill: OrganizationDisasterRecoveryDrill,
) -> OrganizationDisasterRecoveryDrill:
    async with session_factory() as session:
        session.add(drill)
        await session.commit()
    return drill


async def test_drill_stores_lifecycle_and_summary(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    drill = await save(
        session_factory,
        drill_for(
            tenants,
            mode=DisasterRecoveryDrillMode.RESTORE_TEST,
            target_organization_id=tenants.b.id,
            status=DisasterRecoveryDrillStatus.COMPLETED,
            finished_at=NOW + timedelta(minutes=3),
            summary={"documents": 5, "assets": 1},
        ),
    )

    async with session_factory() as session:
        stored = await session.get(OrganizationDisasterRecoveryDrill, drill.id)

    assert stored is not None
    assert stored.mode is DisasterRecoveryDrillMode.RESTORE_TEST
    assert stored.status is DisasterRecoveryDrillStatus.COMPLETED
    assert stored.target_organization_id == tenants.b.id
    assert stored.summary == {"documents": 5, "assets": 1}
    assert stored.created_at is not None and stored.updated_at is not None


@pytest.mark.parametrize("mode", list(DisasterRecoveryDrillMode))
async def test_every_mode_is_stored(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mode: DisasterRecoveryDrillMode,
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    drill = await save(session_factory, drill_for(tenants, mode=mode))

    async with session_factory() as session:
        stored = await session.get(OrganizationDisasterRecoveryDrill, drill.id)
    assert stored is not None and stored.mode is mode


@pytest.mark.parametrize(
    "values",
    [
        {"mode": "sideways"},
        {"status": "unknown"},
        {"organization_id": uuid.uuid4()},
        {"requested_by_user_id": uuid.uuid4()},
        {"backup_export_id": uuid.uuid4()},
    ],
)
async def test_invalid_drill_is_rejected(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    values: dict[str, Any],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    async with session_factory() as session:
        session.add(drill_for(tenants, **values))
        with pytest.raises((IntegrityError, LookupError)):
            await session.flush()


async def test_target_is_optional_for_verification(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    drill = await save(session_factory, drill_for(tenants, target_organization_id=None))

    async with session_factory() as session:
        stored = await session.get(OrganizationDisasterRecoveryDrill, drill.id)
    assert stored is not None and stored.target_organization_id is None


async def test_organization_delete_cascades_drill(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    drill = await save(session_factory, drill_for(tenants))

    async with session_factory() as session:
        await session.execute(delete(Organization).where(Organization.id == tenants.a.id))
        await session.commit()
        assert await session.get(OrganizationDisasterRecoveryDrill, drill.id) is None


async def test_requesting_user_cannot_be_deleted_while_drill_exists(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await save(session_factory, drill_for(tenants))

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(delete(User).where(User.id == tenants.a.owner_id))
