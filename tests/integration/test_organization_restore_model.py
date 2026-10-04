import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.organizations.model import Organization
from signalscope.domain.organizations.restore_record import (
    OrganizationRestore,
    OrganizationRestoreStatus,
)
from signalscope.domain.users.model import User
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
SHA256 = hashlib.sha256(b"organization export").hexdigest()


def restore_for(tenants: Tenants, **values: Any) -> OrganizationRestore:
    fields: dict[str, Any] = {
        "target_organization_id": tenants.a.id,
        "requested_by_user_id": tenants.a.owner_id,
        "source_export_sha256": SHA256,
        "status": OrganizationRestoreStatus.PLANNED,
        "started_at": NOW,
    }
    return OrganizationRestore(**(fields | values))


async def save(
    session_factory: async_sessionmaker[AsyncSession], restore: OrganizationRestore
) -> OrganizationRestore:
    async with session_factory() as session:
        session.add(restore)
        await session.commit()
    return restore


async def test_restore_record_stores_lifecycle_and_safe_summary(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    restore = await save(
        session_factory,
        restore_for(
            tenants,
            status=OrganizationRestoreStatus.COMPLETED,
            finished_at=NOW + timedelta(minutes=2),
            summary={"documents": 12, "assets": 3},
        ),
    )

    async with session_factory() as session:
        stored = await session.get(OrganizationRestore, restore.id)

    assert stored is not None
    assert stored.status is OrganizationRestoreStatus.COMPLETED
    assert stored.source_export_sha256 == SHA256
    assert stored.summary == {"documents": 12, "assets": 3}
    assert stored.finished_at == NOW + timedelta(minutes=2)
    assert stored.created_at is not None and stored.updated_at is not None


@pytest.mark.parametrize("status", list(OrganizationRestoreStatus))
async def test_every_restore_status_is_stored(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    status: OrganizationRestoreStatus,
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    restore = await save(session_factory, restore_for(tenants, status=status))

    async with session_factory() as session:
        stored = await session.get(OrganizationRestore, restore.id)
    assert stored is not None and stored.status is status


@pytest.mark.parametrize(
    "values",
    [
        {"status": "unknown"},
        {"target_organization_id": uuid.uuid4()},
        {"requested_by_user_id": uuid.uuid4()},
        {"source_export_sha256": "not-a-checksum"},
    ],
)
async def test_invalid_restore_record_is_rejected(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    values: dict[str, Any],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    async with session_factory() as session:
        session.add(restore_for(tenants, **values))
        with pytest.raises((IntegrityError, LookupError)):
            await session.flush()


async def test_organization_delete_cascades_restore_record(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    restore = await save(session_factory, restore_for(tenants))

    async with session_factory() as session:
        await session.execute(delete(Organization).where(Organization.id == tenants.a.id))
        await session.commit()
        assert await session.get(OrganizationRestore, restore.id) is None


async def test_requesting_user_cannot_be_deleted_while_restore_exists(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await save(session_factory, restore_for(tenants))

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(delete(User).where(User.id == tenants.a.owner_id))
