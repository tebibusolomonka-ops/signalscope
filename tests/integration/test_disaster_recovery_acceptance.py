import hashlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.diagnostics.acceptance_profile import AcceptanceProfile
from signalscope.domain.diagnostics.disaster_recovery_acceptance import (
    DisasterRecoveryAcceptanceService,
)
from signalscope.domain.organizations.backup_policy import OrganizationBackupPolicy
from signalscope.domain.organizations.drill_record import (
    DisasterRecoveryDrillMode,
    DisasterRecoveryDrillStatus,
    OrganizationDisasterRecoveryDrill,
)
from signalscope.domain.organizations.export_record import (
    OrganizationExport,
    OrganizationExportStatus,
)
from tenancy_helpers import make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


async def test_evidence_is_organization_scoped_and_ignores_failed_drills(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    other_backup = OrganizationExport(
        organization_id=tenants.b.id,
        requested_by_user_id=tenants.b.owner_id,
        status=OrganizationExportStatus.COMPLETED,
        format_version="1",
        started_at=NOW - timedelta(minutes=2),
        finished_at=NOW - timedelta(minutes=1),
        artifact_key="organization-backups/other.zip",
        size_bytes=10,
        sha256=hashlib.sha256(b"other").hexdigest(),
    )
    failed = OrganizationDisasterRecoveryDrill(
        organization_id=tenants.a.id,
        requested_by_user_id=tenants.a.owner_id,
        mode=DisasterRecoveryDrillMode.VERIFICATION_ONLY,
        status=DisasterRecoveryDrillStatus.FAILED,
        started_at=NOW - timedelta(minutes=2),
        finished_at=NOW - timedelta(minutes=1),
        summary={"include_assets": True},
    )
    other_drill = OrganizationDisasterRecoveryDrill(
        organization_id=tenants.b.id,
        requested_by_user_id=tenants.b.owner_id,
        mode=DisasterRecoveryDrillMode.VERIFICATION_ONLY,
        status=DisasterRecoveryDrillStatus.COMPLETED,
        started_at=NOW - timedelta(minutes=2),
        finished_at=NOW - timedelta(minutes=1),
        summary={"include_assets": True},
    )
    async with session_factory() as session:
        session.add_all(
            [
                OrganizationBackupPolicy(organization_id=tenants.b.id, include_assets=True),
                other_backup,
                failed,
                other_drill,
            ]
        )
        await session.commit()
        profile = AcceptanceProfile(
            1,
            {
                "backup": {"verified_backup_exists": True},
                "disaster_recovery": {"verification_drill_exists": True},
            },
        )
        evidence = await DisasterRecoveryAcceptanceService(session, clock=lambda: NOW).collect(
            tenants.a.id, profile
        )

    assert evidence.values["backup.verified_backup_exists"] is False
    assert evidence.values["disaster_recovery.verification_drill_exists"] is False
    assert evidence.references == {}
    assert evidence.facts == {
        "backup": None,
        "disaster_recovery": {
            "verification_drill": None,
            "restore_test_drill": None,
        },
    }
