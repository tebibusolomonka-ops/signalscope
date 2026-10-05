import dataclasses
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.settings import Environment, Settings
from signalscope.domain.diagnostics.acceptance_profile import AcceptanceProfile
from signalscope.domain.diagnostics.deployment_validation import (
    BackupRequirement,
    DeploymentValidationProfile,
)
from signalscope.domain.diagnostics.release_readiness import ReleaseReadinessService
from signalscope.domain.evaluation.model import EvaluationReportRecord
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
from signalscope.storage.local import LocalBlobStore
from tenancy_helpers import make_tenants

pytestmark = pytest.mark.anyio

TENANT_MARKER = "release-readiness-tenant-content-must-not-appear"
PASSWORD = "release-readiness-database-password"


async def test_release_readiness_combines_existing_evidence_without_mutation(
    auth_client: httpx.AsyncClient,
    migrated_database: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    now = datetime.now(UTC)
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()
    settings = dataclasses.replace(
        migrated_database,
        environment=Environment.PRODUCTION,
        auth_enabled=True,
        database_url=f"postgresql+asyncpg://operator:{PASSWORD}@db/signalscope",
        blob_dir=blob_dir,
        build_sha="abc123",
        build_time="2026-10-05T12:00:00Z",
        release_name="final",
    )
    backup = OrganizationExport(
        organization_id=tenants.a.id,
        requested_by_user_id=tenants.a.owner_id,
        status=OrganizationExportStatus.COMPLETED,
        format_version="1",
        started_at=now - timedelta(minutes=6),
        finished_at=now - timedelta(minutes=5),
        artifact_key="organization-backups/release.zip",
        size_bytes=100,
        sha256=hashlib.sha256(b"release").hexdigest(),
    )
    verification = OrganizationDisasterRecoveryDrill(
        organization_id=tenants.a.id,
        requested_by_user_id=tenants.a.owner_id,
        mode=DisasterRecoveryDrillMode.VERIFICATION_ONLY,
        status=DisasterRecoveryDrillStatus.COMPLETED,
        started_at=now - timedelta(minutes=4),
        finished_at=now - timedelta(minutes=3),
        summary={"include_assets": True, "asset_count": 0},
    )
    restore = OrganizationDisasterRecoveryDrill(
        organization_id=tenants.a.id,
        target_organization_id=tenants.b.id,
        requested_by_user_id=tenants.a.owner_id,
        mode=DisasterRecoveryDrillMode.RESTORE_TEST,
        status=DisasterRecoveryDrillStatus.COMPLETED,
        started_at=now - timedelta(minutes=2),
        finished_at=now - timedelta(minutes=1),
        summary={"include_assets": True, "asset_count": 0},
    )
    evaluation = EvaluationReportRecord(
        task="embedding_retrieval",
        model="intfloat/multilingual-e5-small",
        provider="sentence_transformers",
        dataset_name="release",
        dataset_fingerprint="release-data-v1",
        report_version=1,
        report_json={
            "metrics": {"recall@5": 0.8},
            "quality_gate_result": {"passed": True},
        },
        report_sha256="b" * 64,
        environment_summary={"python": "3.12"},
    )
    async with session_factory() as session:
        session.add_all(
            [
                OrganizationBackupPolicy(organization_id=tenants.a.id, include_assets=True),
                backup,
                verification,
                restore,
                evaluation,
            ]
        )
        await session.commit()

    acceptance_profile = AcceptanceProfile(
        1,
        {
            "deployment": {
                "production_configuration_valid": True,
                "migration_current": True,
                "validation_passes": True,
            },
            "security": {
                "auth_enabled": True,
                "login_throttling_configured": True,
                "absolute_session_expiry_configured": True,
                "idle_session_expiry_configured": True,
                "security_headers_enabled": True,
                "csp_enabled": True,
                "support_bundle_redaction_succeeds": True,
            },
            "backup": {"verified_backup_exists": True, "max_age_hours": 24},
            "disaster_recovery": {
                "verification_drill_exists": True,
                "verification_max_age_hours": 24,
                "restore_test_required": True,
                "restore_test_max_age_hours": 24,
                "asset_verification_succeeded": True,
            },
            "operations": {
                "startup_preflight_passes": True,
                "support_bundle_works": True,
            },
            "model_evaluation": {"quality_gate_evidence_exists": True},
        },
    )
    deployment_profile = DeploymentValidationProfile(
        1,
        True,
        True,
        True,
        True,
        True,
        BackupRequirement(True, 24),
    )
    async with session_factory() as session:
        before = {
            "backups": await session.scalar(select(func.count()).select_from(OrganizationExport)),
            "drills": await session.scalar(
                select(func.count()).select_from(OrganizationDisasterRecoveryDrill)
            ),
            "evaluations": await session.scalar(
                select(func.count()).select_from(EvaluationReportRecord)
            ),
        }
        report = await ReleaseReadinessService(settings).collect(
            acceptance_profile,
            session=session,
            blobs=LocalBlobStore(blob_dir),
            organization_id=tenants.a.id,
            deployment_profile=deployment_profile,
        )
        after = {
            "backups": await session.scalar(select(func.count()).select_from(OrganizationExport)),
            "drills": await session.scalar(
                select(func.count()).select_from(OrganizationDisasterRecoveryDrill)
            ),
            "evaluations": await session.scalar(
                select(func.count()).select_from(EvaluationReportRecord)
            ),
        }

    payload = report.to_dict()
    rendered = str(payload)
    assert report.acceptance.passed is True
    assert payload["acceptance"]["requirements_missed"] == []
    assert payload["pilot_readiness"]["manual"]
    assert payload["latest_verified_backup_evidence"]["id"] == str(backup.id)
    assert payload["disaster_recovery_evidence"]["restore_test_drill"]["id"] == str(restore.id)
    assert payload["model_evaluation_evidence"]["reports"] == [
        {
            "report_id": str(evaluation.id),
            "task": "embedding_retrieval",
            "model": "intfloat/multilingual-e5-small",
            "provider": "sentence_transformers",
            "dataset_fingerprint": "release-data-v1",
            "created_at": evaluation.created_at.isoformat(),
            "quality_gate_evidence_available": True,
            "quality_gate_passed": True,
        }
    ]
    assert before == after
    assert PASSWORD not in rendered
    assert TENANT_MARKER not in rendered
    assert "artifact_key" not in rendered
    assert payload["pilot_readiness"]["model"]["configured"] is False


async def test_release_readiness_reports_missing_evidence(
    auth_client: httpx.AsyncClient,
    migrated_database: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    profile = AcceptanceProfile(
        1,
        {
            "backup": {"verified_backup_exists": True},
            "disaster_recovery": {"restore_test_required": True},
            "model_evaluation": {"quality_gate_evidence_exists": True},
        },
    )
    async with session_factory() as session:
        report = await ReleaseReadinessService(migrated_database).collect(
            profile,
            session=session,
            blobs=None,
            organization_id=tenants.a.id,
        )

    assert set(report.acceptance.to_dict()["requirements_missed"]) == {
        "backup.verified_backup_exists",
        "disaster_recovery.restore_test_required",
        "model_evaluation.quality_gate_evidence_exists",
    }
