import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.pilot_readiness import CheckStatus, PilotReadinessEvaluator
from signalscope.domain.diagnostics.support_bundle import SupportBundleService
from signalscope.domain.organizations.export_archive import OrganizationExportArchiveService
from signalscope.domain.organizations.export_inventory import OrganizationExportInventoryService
from signalscope.domain.organizations.export_verification import (
    OrganizationExportVerificationService,
)
from signalscope.domain.organizations.restore_plan import build_restore_plan
from signalscope.domain.sources.model import Source
from signalscope.storage.local import LocalBlobStore
from tenancy_helpers import add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio

TENANT_TEXT = "PILOT_TENANT_SENTENCE_marker"


@pytest.fixture
async def pilot_client(
    migrated_database: Settings, tmp_path: Path
) -> AsyncIterator[tuple[Settings, httpx.AsyncClient]]:
    settings = dataclasses.replace(
        migrated_database, auth_enabled=True, blob_dir=tmp_path / "blobs"
    )
    app = create_app(settings)
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield settings, client


def pilot_statuses(report: object) -> dict[str, CheckStatus]:
    return {check.name: check.status for check in report.checks}  # type: ignore[attr-defined]


async def test_pilot_preparation_end_to_end(
    pilot_client: tuple[Settings, httpx.AsyncClient],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings, client = pilot_client
    blobs = LocalBlobStore(settings.blob_dir)
    tenants = await make_tenants(client, session_factory)

    # Organization with a source and a document that carries tenant text.
    source_id = await add_source(session_factory, tenants.a.id, "Pilot source")
    await add_document(session_factory, source_id, "Pilot doc", [TENANT_TEXT])

    # A manual backup runs and completes.
    backup = await client.post(f"/organizations/{tenants.a.id}/backups/run", headers=tenants.system)
    assert backup.status_code == 201
    assert backup.json()["status"] == "completed"

    # The export archive verifies, and a restore dry run into empty B has no conflicts.
    async with session_factory() as session:
        archive = await OrganizationExportArchiveService(
            OrganizationExportInventoryService(session), blobs
        ).build(tenants.a.id)
    assert OrganizationExportVerificationService().verify(archive.data).valid
    async with session_factory() as session:
        plan = await build_restore_plan(session, archive.data, tenants.b.id)
    assert list(plan["conflicts"]) == []

    # Readiness answers 200 and carries the security headers and CSP.
    ready = await client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in ready.headers

    # The support bundle holds no tenant content and no database URL.
    async with session_factory() as session:
        bundle = await SupportBundleService(settings).build(session, blobs)
    assert TENANT_TEXT.encode() not in bundle
    assert settings.database_url is not None
    assert settings.database_url.encode() not in bundle

    # Pilot readiness confirms the migration and dependencies.
    async with session_factory() as session:
        report = await PilotReadinessEvaluator(settings).evaluate(session, blobs)
    statuses = pilot_statuses(report)
    assert statuses["migration"] is CheckStatus.PASSED
    assert statuses["readiness_database"] is CheckStatus.PASSED
    assert statuses["readiness_storage"] is CheckStatus.PASSED

    # Tenant isolation holds: the restore target organization B stays empty.
    async with session_factory() as session:
        b_sources = await session.scalar(
            select(func.count()).select_from(Source).where(Source.organization_id == tenants.b.id)
        )
    assert b_sources == 0
