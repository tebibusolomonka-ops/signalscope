import dataclasses
import io
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.cli import restore_organization
from signalscope.core.settings import Settings
from signalscope.domain.organizations.export_archive import OrganizationExportArchiveService
from signalscope.domain.organizations.export_inventory import OrganizationExportInventoryService
from signalscope.domain.sources.model import Source
from tenancy_helpers import add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings(migrated_database: Settings, tmp_path: Path) -> Settings:
    return dataclasses.replace(migrated_database, blob_dir=tmp_path / "blobs")


async def make_archive(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID,
) -> Path:
    source_id = await add_source(session_factory, organization_id, "Archived feed")
    await add_document(session_factory, source_id, "Archived report", ["Harbour rose."])
    async with session_factory() as session:
        archive = await OrganizationExportArchiveService(
            OrganizationExportInventoryService(session), None
        ).build(organization_id, include_assets=False)
    assert settings.blob_dir is not None
    path = settings.blob_dir.parent / "tenant.zip"
    path.write_bytes(archive.data)
    return path


async def run(
    path: Path, organization_id: uuid.UUID, settings: Settings, **options: Any
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await restore_organization(path, organization_id, settings, out, err, **options)
    return code, out.getvalue(), err.getvalue()


async def test_dry_run_plans_without_changing_data(
    settings: Settings,
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    path = await make_archive(settings, session_factory, tenants.a.id)

    code, out, err = await run(path, tenants.b.id, settings)

    assert code == 0
    assert "Dry run" in out
    async with session_factory() as session:
        restored = await session.scalar(
            select(Source).where(Source.organization_id == tenants.b.id)
        )
    assert restored is None


async def test_apply_restores_content(
    settings: Settings,
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    path = await make_archive(settings, session_factory, tenants.a.id)

    code, out, err = await run(path, tenants.b.id, settings, apply=True)

    assert code == 0, err
    assert "Status: completed" in out
    async with session_factory() as session:
        restored = await session.scalar(
            select(Source).where(Source.organization_id == tenants.b.id)
        )
    assert restored is not None and restored.name == "Archived feed"
