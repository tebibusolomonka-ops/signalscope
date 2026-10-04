import dataclasses
import io
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.cli import run_disaster_recovery_drill
from signalscope.core.settings import Settings
from tenancy_helpers import add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings(migrated_database: Settings, tmp_path: Path) -> Settings:
    return dataclasses.replace(migrated_database, blob_dir=tmp_path / "blobs")


async def run(organization_id: Any, settings: Settings, **options: Any) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await run_disaster_recovery_drill(organization_id, settings, out, err, **options)
    return code, out.getvalue(), err.getvalue()


async def test_verification_drill_completes(
    settings: Settings,
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    source_id = await add_source(session_factory, tenants.a.id, "Drill source")
    await add_document(session_factory, source_id, "Drill doc", ["Harbour rose."])

    code, out, err = await run(tenants.a.id, settings)

    assert code == 0, err
    assert "Status: completed" in out


async def test_restore_test_drill_completes(
    settings: Settings,
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    source_id = await add_source(session_factory, tenants.a.id, "Drill source")
    await add_document(session_factory, source_id, "Drill doc", ["Harbour rose."])

    code, out, err = await run(
        tenants.a.id, settings, mode="restore-test", target_organization_id=tenants.b.id
    )

    assert code == 0, err
    assert "Mode: restore_test" in out
    assert "Status: completed" in out
