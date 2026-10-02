import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.organizations.export_record import (
    OrganizationExport,
    OrganizationExportStatus,
)
from signalscope.domain.organizations.model import Organization
from signalscope.domain.users.model import User
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
SHA256 = hashlib.sha256(b"archive").hexdigest()


def export_for(tenants: Tenants, **values: Any) -> OrganizationExport:
    fields: dict[str, Any] = {
        "organization_id": tenants.a.id,
        "requested_by_user_id": tenants.owner.id,
        "status": OrganizationExportStatus.PENDING,
        "format_version": "1",
    }
    return OrganizationExport(**(fields | values))


async def save(
    session_factory: async_sessionmaker[AsyncSession], export: OrganizationExport
) -> OrganizationExport:
    async with session_factory() as session:
        session.add(export)
        await session.commit()
    return export


async def test_export_record_stores_lifecycle_and_artifact_metadata(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    export = await save(
        session_factory,
        export_for(
            tenants,
            status=OrganizationExportStatus.COMPLETED,
            started_at=NOW,
            finished_at=NOW + timedelta(minutes=1),
            expires_at=NOW + timedelta(days=7),
            artifact_key=f"organization-exports/{uuid.uuid4()}.zip",
            size_bytes=1024,
            sha256=SHA256,
        ),
    )

    async with session_factory() as session:
        stored = await session.get(OrganizationExport, export.id)

    assert stored is not None
    assert (stored.status, stored.format_version) == (OrganizationExportStatus.COMPLETED, "1")
    assert (stored.started_at, stored.finished_at) == (NOW, NOW + timedelta(minutes=1))
    assert (stored.size_bytes, stored.sha256) == (1024, SHA256)
    assert stored.created_at is not None and stored.updated_at is not None


@pytest.mark.parametrize("status", list(OrganizationExportStatus))
async def test_every_export_status_is_stored(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    status: OrganizationExportStatus,
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    export = await save(session_factory, export_for(tenants, status=status))

    async with session_factory() as session:
        stored = await session.get(OrganizationExport, export.id)
    assert stored is not None and stored.status is status


@pytest.mark.parametrize(
    "values",
    [
        {"status": "unknown"},
        {"organization_id": uuid.uuid4()},
        {"requested_by_user_id": uuid.uuid4()},
        {"size_bytes": -1},
        {"sha256": "not-a-checksum"},
    ],
)
async def test_invalid_export_record_is_rejected(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    values: dict[str, Any],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    async with session_factory() as session:
        session.add(export_for(tenants, **values))
        with pytest.raises((IntegrityError, LookupError)):
            await session.flush()


async def test_organization_delete_cascades_export_record(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    export = await save(session_factory, export_for(tenants))

    async with session_factory() as session:
        await session.execute(delete(Organization).where(Organization.id == tenants.a.id))
        await session.commit()
        assert await session.get(OrganizationExport, export.id) is None


async def test_requesting_user_cannot_be_deleted_while_export_exists(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await save(session_factory, export_for(tenants))

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(delete(User).where(User.id == tenants.owner.id))
