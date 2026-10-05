import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import ConflictError
from signalscope.domain.organizations.backup_service import OrganizationBackupService
from signalscope.domain.organizations.drill_record import (
    DisasterRecoveryDrillMode,
    DisasterRecoveryDrillStatus,
    OrganizationDisasterRecoveryDrill,
)
from signalscope.domain.organizations.export_record import (
    OrganizationExport,
    OrganizationExportStatus,
)
from signalscope.domain.organizations.restore_record import (
    OrganizationRestore,
    OrganizationRestoreStatus,
)
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


class MemoryBlobs:
    async def put(self, key: str, data: bytes) -> None:
        return None

    async def get(self, key: str) -> bytes:
        raise KeyError(key)

    async def delete(self, key: str) -> None:
        return None

    async def exists(self, key: str) -> bool:
        return False


def export_for(
    tenants: Tenants,
    organization_id: uuid.UUID,
    status: OrganizationExportStatus,
) -> OrganizationExport:
    return OrganizationExport(
        organization_id=organization_id,
        requested_by_user_id=tenants.a.owner_id,
        status=status,
        format_version="2",
        started_at=NOW,
    )


def restore_for(
    tenants: Tenants,
    target_organization_id: uuid.UUID,
    status: OrganizationRestoreStatus,
) -> OrganizationRestore:
    return OrganizationRestore(
        target_organization_id=target_organization_id,
        requested_by_user_id=tenants.a.owner_id,
        source_export_sha256="a" * 64,
        status=status,
        started_at=NOW,
    )


def drill_for(
    tenants: Tenants,
    target_organization_id: uuid.UUID,
    status: DisasterRecoveryDrillStatus,
) -> OrganizationDisasterRecoveryDrill:
    return OrganizationDisasterRecoveryDrill(
        organization_id=tenants.a.id,
        target_organization_id=target_organization_id,
        requested_by_user_id=tenants.a.owner_id,
        mode=DisasterRecoveryDrillMode.RESTORE_TEST,
        status=status,
        started_at=NOW,
    )


async def test_active_export_guard_allows_terminal_history_and_other_organizations(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                export_for(tenants, tenants.a.id, OrganizationExportStatus.COMPLETED),
                export_for(tenants, tenants.a.id, OrganizationExportStatus.FAILED),
                export_for(tenants, tenants.a.id, OrganizationExportStatus.RUNNING),
                export_for(tenants, tenants.b.id, OrganizationExportStatus.RUNNING),
            ]
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(ConflictError, match="already running"):
            await OrganizationBackupService(session, MemoryBlobs()).run(
                tenants.a.id, tenants.a.owner_id
            )


async def test_database_blocks_two_active_restores_for_one_target(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                restore_for(tenants, tenants.a.id, OrganizationRestoreStatus.COMPLETED),
                restore_for(tenants, tenants.a.id, OrganizationRestoreStatus.FAILED),
                restore_for(tenants, tenants.a.id, OrganizationRestoreStatus.RUNNING),
                restore_for(tenants, tenants.b.id, OrganizationRestoreStatus.PLANNED),
            ]
        )
        await session.commit()

    async with session_factory() as session:
        session.add(restore_for(tenants, tenants.a.id, OrganizationRestoreStatus.PLANNED))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_database_blocks_two_running_restore_tests_for_one_target(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                drill_for(tenants, tenants.a.id, DisasterRecoveryDrillStatus.COMPLETED),
                drill_for(tenants, tenants.a.id, DisasterRecoveryDrillStatus.FAILED),
                drill_for(tenants, tenants.a.id, DisasterRecoveryDrillStatus.RUNNING),
                drill_for(tenants, tenants.b.id, DisasterRecoveryDrillStatus.RUNNING),
            ]
        )
        await session.commit()

    async with session_factory() as session:
        session.add(drill_for(tenants, tenants.a.id, DisasterRecoveryDrillStatus.RUNNING))
        with pytest.raises(IntegrityError):
            await session.commit()
