import hashlib
import uuid

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import InvalidInputError, ServiceUnavailableError
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.organizations.drill_record import (
    DisasterRecoveryDrillMode,
    DisasterRecoveryDrillStatus,
)
from signalscope.domain.organizations.drill_service import (
    OrganizationDisasterRecoveryDrillService,
)
from signalscope.domain.sources.model import Source
from tenancy_helpers import add_document, add_findings, add_source, make_tenants

pytestmark = pytest.mark.anyio

ASSET = b"drill asset bytes"


class MemoryBlobs:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.values[key] = data

    async def get(self, key: str) -> bytes:
        return self.values[key]

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.values


class FailingAssetBlobs(MemoryBlobs):
    async def put(self, key: str, data: bytes) -> None:
        if key.startswith("document-assets/"):
            raise ServiceUnavailableError("Asset storage is unavailable.")
        await super().put(key, data)


async def build_source_org(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID,
    blobs: MemoryBlobs,
) -> None:
    source_id = await add_source(session_factory, organization_id, "Drill source")
    document_id, chunk_ids = await add_document(
        session_factory, source_id, "Drill doc", ["Harbour rose."]
    )
    await add_findings(session_factory, chunk_ids[0])
    async with session_factory() as session:
        asset = DocumentAsset(
            document_id=document_id,
            storage_key=f"document-assets/{uuid.uuid4()}",
            filename="e.bin",
            content_type="application/octet-stream",
            size_bytes=len(ASSET),
            sha256=hashlib.sha256(ASSET).hexdigest(),
        )
        session.add(asset)
        await session.commit()
        blobs.values[asset.storage_key] = ASSET


async def test_verification_only_drill_completes_without_mutation(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    blobs = MemoryBlobs()
    await build_source_org(session_factory, tenants.a.id, blobs)

    async with session_factory() as session:
        drill = await OrganizationDisasterRecoveryDrillService(session, blobs).run(
            tenants.a.id,
            tenants.a.owner_id,
            mode=DisasterRecoveryDrillMode.VERIFICATION_ONLY,
        )

    assert drill.status is DisasterRecoveryDrillStatus.COMPLETED
    assert drill.summary["plan_conflicts"] == []
    assert drill.finished_at is not None
    # No target content was created.
    async with session_factory() as session:
        b_sources = await session.scalar(
            select(func.count()).select_from(Source).where(Source.organization_id == tenants.b.id)
        )
    assert b_sources == 0


async def test_restore_test_drill_restores_into_empty_target(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    blobs = MemoryBlobs()
    await build_source_org(session_factory, tenants.a.id, blobs)

    async with session_factory() as session:
        drill = await OrganizationDisasterRecoveryDrillService(session, blobs).run(
            tenants.a.id,
            tenants.a.owner_id,
            mode=DisasterRecoveryDrillMode.RESTORE_TEST,
            target_organization_id=tenants.b.id,
        )

    assert drill.status is DisasterRecoveryDrillStatus.COMPLETED
    assert drill.restore_id is not None
    async with session_factory() as session:
        b_sources = await session.scalar(
            select(func.count()).select_from(Source).where(Source.organization_id == tenants.b.id)
        )
        a_sources = await session.scalar(
            select(func.count()).select_from(Source).where(Source.organization_id == tenants.a.id)
        )
    assert b_sources == 1
    assert a_sources == 1  # source organization unchanged


async def test_restore_test_requires_a_target(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    blobs = MemoryBlobs()
    await build_source_org(session_factory, tenants.a.id, blobs)

    async with session_factory() as session:
        with pytest.raises(InvalidInputError, match="empty target"):
            await OrganizationDisasterRecoveryDrillService(session, blobs).run(
                tenants.a.id,
                tenants.a.owner_id,
                mode=DisasterRecoveryDrillMode.RESTORE_TEST,
            )


async def test_restore_test_refuses_non_empty_target(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    blobs = MemoryBlobs()
    await build_source_org(session_factory, tenants.a.id, blobs)
    await add_source(session_factory, tenants.b.id, "Existing")

    async with session_factory() as session:
        drill = await OrganizationDisasterRecoveryDrillService(session, blobs).run(
            tenants.a.id,
            tenants.a.owner_id,
            mode=DisasterRecoveryDrillMode.RESTORE_TEST,
            target_organization_id=tenants.b.id,
        )

    assert drill.status is DisasterRecoveryDrillStatus.FAILED
    assert drill.safe_error and "not ready" in drill.safe_error


async def test_restore_test_marks_failed_when_storage_fails(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    blobs = FailingAssetBlobs()
    await build_source_org(session_factory, tenants.a.id, blobs)

    async with session_factory() as session:
        drill = await OrganizationDisasterRecoveryDrillService(session, blobs).run(
            tenants.a.id,
            tenants.a.owner_id,
            mode=DisasterRecoveryDrillMode.RESTORE_TEST,
            target_organization_id=tenants.b.id,
        )

    assert drill.status is DisasterRecoveryDrillStatus.FAILED
    async with session_factory() as session:
        b_sources = await session.scalar(
            select(func.count()).select_from(Source).where(Source.organization_id == tenants.b.id)
        )
    assert b_sources == 0
