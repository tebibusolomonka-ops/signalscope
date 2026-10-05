import hashlib
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import ConflictError, InvalidInputError, ServiceUnavailableError
from signalscope.domain.claims.model import ClaimEvidence
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.organizations.export_archive import OrganizationExportArchiveService
from signalscope.domain.organizations.export_inventory import OrganizationExportInventoryService
from signalscope.domain.organizations.restore_record import (
    OrganizationRestore,
    OrganizationRestoreStatus,
)
from signalscope.domain.organizations.restore_service import OrganizationRestoreService
from signalscope.domain.sources.model import Source
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.model import User
from signalscope.domain.users.session import UserSession
from signalscope.domain.users.throttle import AuthenticationThrottle
from tenancy_helpers import add_document, add_findings, add_source, make_tenants

pytestmark = pytest.mark.anyio


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


async def archive_with_asset(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID
) -> tuple[bytes, bytes, uuid.UUID, uuid.UUID, uuid.UUID]:
    source_id = await add_source(session_factory, organization_id, "Archive source")
    document_id, chunk_ids = await add_document(
        session_factory, source_id, "Archive document", ["Port rose after the storm."]
    )
    entity_id, claim_id = await add_findings(session_factory, chunk_ids[0])
    assert claim_id is not None
    content = b"original asset bytes"
    async with session_factory() as session:
        asset = DocumentAsset(
            document_id=document_id,
            storage_key=f"document-assets/{uuid.uuid4()}",
            filename="report.txt",
            content_type="text/plain",
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        session.add(asset)
        await session.commit()
        source_asset_key = asset.storage_key

    blobs = MemoryBlobs()
    blobs.values[source_asset_key] = content
    async with session_factory() as session:
        archive = await OrganizationExportArchiveService(
            OrganizationExportInventoryService(session), blobs
        ).build(organization_id)
    return archive.data, content, document_id, entity_id, claim_id


async def test_restore_into_empty_organization_preserves_content_and_isolation(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    (
        data,
        asset_content,
        source_document_id,
        source_entity_id,
        source_claim_id,
    ) = await archive_with_asset(session_factory, tenants.a.id)
    blobs = MemoryBlobs()
    async with session_factory() as session:
        credentials_before = tuple(
            await session.scalars(
                select(UserPasswordCredential).order_by(UserPasswordCredential.user_id)
            )
        )
        credential_values = [(item.user_id, item.password_hash) for item in credentials_before]
        sessions_before = await session.scalar(select(func.count()).select_from(UserSession))
        throttles_before = await session.scalar(
            select(func.count()).select_from(AuthenticationThrottle)
        )
        restore = await OrganizationRestoreService(session, blobs).restore(
            data, tenants.b.id, tenants.b.owner_id
        )

    async with session_factory() as session:
        stored = await session.get(OrganizationRestore, restore.id)
        restored_source = await session.scalar(
            select(Source).where(Source.organization_id == tenants.b.id)
        )
        restored_document = await session.scalar(
            select(Document).where(Document.source_id == restored_source.id)
        )
        restored_asset = await session.scalar(
            select(DocumentAsset).where(DocumentAsset.document_id == restored_document.id)
        )
        entity_ids = set(
            await session.scalars(
                select(EntityMention.entity_id).where(
                    EntityMention.document_id == restored_document.id
                )
            )
        )
        claim_ids = set(
            await session.scalars(
                select(ClaimEvidence.claim_id).where(
                    ClaimEvidence.chunk_id.in_(
                        select(ClaimEvidence.chunk_id).join(
                            Document, Document.id == restored_document.id
                        )
                    )
                )
            )
        )
        credentials_after = tuple(
            await session.scalars(
                select(UserPasswordCredential).order_by(UserPasswordCredential.user_id)
            )
        )
        session_count = await session.scalar(select(func.count()).select_from(UserSession))
        throttle_count = await session.scalar(
            select(func.count()).select_from(AuthenticationThrottle)
        )

    assert stored is not None and stored.status is OrganizationRestoreStatus.COMPLETED
    assert restored_source is not None and restored_source.id != source_document_id
    assert restored_document is not None and restored_document.id != source_document_id
    assert restored_asset is not None
    assert restored_asset.storage_key.startswith(f"document-assets/{tenants.b.id}/")
    assert blobs.values[restored_asset.storage_key] == asset_content
    assert source_entity_id in entity_ids
    assert source_claim_id in claim_ids
    assert [(item.user_id, item.password_hash) for item in credentials_after] == credential_values
    assert session_count == sessions_before
    assert throttle_count == throttles_before
    assert not any(key.startswith("organization-restore-staging/") for key in blobs.values)


async def test_restore_refuses_populated_target_before_writing_record(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    data, *_ = await archive_with_asset(session_factory, tenants.a.id)
    await add_source(session_factory, tenants.b.id, "Existing target source")

    async with session_factory() as session:
        with pytest.raises(InvalidInputError, match="must be empty"):
            await OrganizationRestoreService(session, MemoryBlobs()).restore(
                data, tenants.b.id, tenants.b.owner_id
            )
        count = await session.scalar(select(func.count()).select_from(OrganizationRestore))

    assert count == 0


async def test_restore_blocks_a_second_active_operation_for_the_target(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    data, *_ = await archive_with_asset(session_factory, tenants.a.id)
    async with session_factory() as session:
        session.add(
            OrganizationRestore(
                target_organization_id=tenants.b.id,
                requested_by_user_id=tenants.b.owner_id,
                source_export_sha256="a" * 64,
                status=OrganizationRestoreStatus.RUNNING,
                started_at=datetime.now(UTC),
            )
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(ConflictError, match="already active"):
            await OrganizationRestoreService(session, MemoryBlobs()).restore(
                data, tenants.b.id, tenants.b.owner_id
            )


async def test_restore_requires_all_asset_content(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    source_id = await add_source(session_factory, tenants.a.id)
    document_id, _ = await add_document(session_factory, source_id, "No binary", ["text"])
    async with session_factory() as session:
        session.add(
            DocumentAsset(
                document_id=document_id,
                storage_key=f"document-assets/{uuid.uuid4()}",
                content_type="text/plain",
                size_bytes=4,
                sha256=hashlib.sha256(b"text").hexdigest(),
            )
        )
        await session.commit()
        archive = await OrganizationExportArchiveService(
            OrganizationExportInventoryService(session), MemoryBlobs()
        ).build(tenants.a.id, include_assets=False)

    async with session_factory() as session:
        with pytest.raises(InvalidInputError, match="content is missing"):
            await OrganizationRestoreService(session, MemoryBlobs()).restore(
                archive.data, tenants.b.id, tenants.b.owner_id
            )


async def test_restore_refuses_inactive_mapped_user_before_writing_record(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    data, *_ = await archive_with_asset(session_factory, tenants.a.id)
    async with session_factory() as session:
        owner = await session.get_one(User, tenants.a.owner_id)
        owner.is_active = False
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(InvalidInputError, match="active user mapping"):
            await OrganizationRestoreService(session, MemoryBlobs()).restore(
                data, tenants.b.id, tenants.b.owner_id
            )
        count = await session.scalar(select(func.count()).select_from(OrganizationRestore))

    assert count == 0


class FailingAssetBlobs(MemoryBlobs):
    """Stores staging bytes but refuses the final document asset write."""

    async def put(self, key: str, data: bytes) -> None:
        if key.startswith("document-assets/"):
            raise ServiceUnavailableError("Asset storage is unavailable.")
        await super().put(key, data)


async def test_restore_marks_record_failed_and_cleans_assets_on_storage_failure(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    data, *_ = await archive_with_asset(session_factory, tenants.a.id)
    blobs = FailingAssetBlobs()

    async with session_factory() as session:
        with pytest.raises(ServiceUnavailableError):
            await OrganizationRestoreService(session, blobs).restore(
                data, tenants.b.id, tenants.b.owner_id
            )

    async with session_factory() as session:
        restore = await session.scalar(select(OrganizationRestore))
        restored_source = await session.scalar(
            select(Source).where(Source.organization_id == tenants.b.id)
        )

    assert restore is not None and restore.status is OrganizationRestoreStatus.FAILED
    assert restore.finished_at is not None and restore.safe_error
    assert restored_source is None
    assert not any(key.startswith("organization-restore-staging/") for key in blobs.values)
    assert not any(key.startswith(f"document-assets/{tenants.b.id}/") for key in blobs.values)
