import dataclasses
import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.deployment import DeploymentDiagnosticsService
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio


async def test_collect_reports_ready_and_up_to_date(
    migrated_database: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = dataclasses.replace(migrated_database, blob_dir=tmp_path / "blobs")
    service = DeploymentDiagnosticsService(settings)
    async with session_factory() as session:
        report = await service.collect(session, LocalBlobStore(settings.blob_dir))

    assert report.readiness is not None and report.readiness.ready is True
    assert len(report.queues) == 6
    assert report.migration_current is not None
    assert report.migration_current == report.migration_head
    assert report.migration_up_to_date is True

    # No secret from the database URL leaks into the serialized report.
    assert settings.database_url is not None
    assert settings.database_url not in json.dumps(report.to_dict())
