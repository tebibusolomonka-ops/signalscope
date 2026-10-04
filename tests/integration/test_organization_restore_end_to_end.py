import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.revision import DocumentRevision
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.investigations.item import InvestigationItem, InvestigationItemType
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.organizations.export_archive import OrganizationExportArchiveService
from signalscope.domain.organizations.export_inventory import OrganizationExportInventoryService
from signalscope.domain.organizations.export_verification import (
    OrganizationExportVerificationService,
)
from signalscope.domain.organizations.invitation import InvitationRole, OrganizationInvitation
from signalscope.domain.organizations.membership import OrganizationMembership
from signalscope.domain.organizations.restore_plan import build_restore_plan
from signalscope.domain.organizations.restore_record import OrganizationRestoreStatus
from signalscope.domain.organizations.restore_service import OrganizationRestoreService
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.research.turn import ResearchTurn
from signalscope.domain.sources.model import Source, SourceType
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.session import UserSession
from signalscope.domain.users.throttle import AuthenticationThrottle
from tenancy_helpers import make_tenants

pytestmark = pytest.mark.anyio

ASSET_BYTES = b"binary asset for the end to end restore test"


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


@dataclass
class OrgA:
    source_id: uuid.UUID
    document_id: uuid.UUID
    entity_id: uuid.UUID
    claim_id: uuid.UUID
    asset_sha256: str
    invited_by: uuid.UUID


async def build_org_a(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID,
    owner_id: uuid.UUID,
    blobs: MemoryBlobs,
) -> OrgA:
    async with session_factory() as session:
        entity = Entity(canonical_name="Harbour", normalized_name="harbour", entity_type="place")
        claim = Claim(text="Water rose fast", normalized_text="water rose fast", claim_type="fact")
        source = Source(
            type=SourceType.WEB,
            name="Alpha feed",
            url="https://example.org/alpha",
            organization_id=organization_id,
        )
        session.add_all([entity, claim, source])
        await session.flush()

        text = "The harbour flooded after the storm."
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        document = Document(source_id=source.id, title="Alpha report", content=text)
        session.add(document)
        await session.flush()
        chunk = DocumentChunk(
            document_id=document.id,
            position=0,
            text=text,
            start_char=0,
            end_char=len(text),
            text_hash=text_hash,
        )
        session.add(chunk)
        await session.flush()

        session.add(
            DocumentRevision(document_id=document.id, version=1, title="Alpha report", content=text)
        )
        asset_sha = hashlib.sha256(ASSET_BYTES).hexdigest()
        asset = DocumentAsset(
            document_id=document.id,
            storage_key=f"document-assets/{uuid.uuid4()}",
            filename="evidence.bin",
            content_type="application/octet-stream",
            size_bytes=len(ASSET_BYTES),
            sha256=asset_sha,
        )
        session.add(asset)
        session.add(
            EntityMention(
                entity_id=entity.id,
                document_id=document.id,
                chunk_id=chunk.id,
                surface_text="harbour",
                entity_type="place",
                start_char=0,
                end_char=7,
                provider="test",
                model="m",
                chunk_text_hash=text_hash,
            )
        )
        session.add(
            ClaimEvidence(
                claim_id=claim.id,
                chunk_id=chunk.id,
                surface_text="rose fast",
                start_char=10,
                end_char=19,
                provider="test",
                model="m",
            )
        )

        event = Event(event_type="flood", title="Alpha flood")
        cluster = EventCluster(
            event_type="flood",
            canonical_title="Alpha flood",
            normalized_title="alpha flood",
            organization_id=organization_id,
        )
        session.add_all([event, cluster])
        await session.flush()
        session.add(EventEvidence(event_id=event.id, chunk_id=chunk.id, provider="test", model="m"))
        session.add(EventClusterMember(event_id=event.id, cluster_id=cluster.id))

        research = ResearchSession(
            title="Alpha questions", source_id=source.id, organization_id=organization_id
        )
        session.add(research)
        await session.flush()
        session.add(
            ResearchTurn(
                session_id=research.id,
                sequence=1,
                question="What happened?",
                answer="The harbour flooded [E1].",
                citation_ids=["E1"],
            )
        )

        investigation = Investigation(
            title="Alpha investigation",
            organization_id=organization_id,
            created_by_user_id=owner_id,
        )
        session.add(investigation)
        await session.flush()
        session.add(
            InvestigationItem(
                investigation_id=investigation.id,
                item_type=InvestigationItemType.SOURCE,
                reference_id=source.id,
            )
        )

        session.add(
            OrganizationInvitation(
                organization_id=organization_id,
                normalized_email="guest@example.org",
                role=InvitationRole.MEMBER,
                token_hash="a" * 64,
                expires_at=datetime.now(UTC) + timedelta(days=1),
                invited_by_user_id=owner_id,
            )
        )
        await session.commit()
        blobs.values[asset.storage_key] = ASSET_BYTES
        return OrgA(source.id, document.id, entity.id, claim.id, asset_sha, owner_id)


async def count(session_factory: async_sessionmaker[AsyncSession], model: type) -> int:
    async with session_factory() as session:
        value = await session.scalar(select(func.count()).select_from(model))
    return value or 0


async def test_restore_rebuilds_organization_without_restoring_secrets(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    blobs = MemoryBlobs()
    a = await build_org_a(session_factory, tenants.a.id, tenants.a.owner_id, blobs)
    mapped_owner = await create_account(session_factory, "restored-owner@example.org")

    async with session_factory() as session:
        session.add(
            AuthenticationThrottle(
                identifier="b" * 64, failure_count=2, window_started_at=datetime.now(UTC)
            )
        )
        await session.commit()

    # Export Organization A with its binary assets, then verify the archive.
    async with session_factory() as session:
        archive = await OrganizationExportArchiveService(
            OrganizationExportInventoryService(session), blobs
        ).build(tenants.a.id)
    assert OrganizationExportVerificationService().verify(archive.data).valid

    credentials_before = await count(session_factory, UserPasswordCredential)
    sessions_before = await count(session_factory, UserSession)
    throttles_before = await count(session_factory, AuthenticationThrottle)
    sources_a_before = await count(session_factory, Source)

    # Plan the restore into empty Organization B.
    async with session_factory() as session:
        plan = await build_restore_plan(session, archive.data, tenants.b.id)
    assert plan["conflicts"] == []

    # Map Organization A's owner to a different existing user, then apply.
    restore_blobs = MemoryBlobs()
    async with session_factory() as session:
        restore = await OrganizationRestoreService(session, restore_blobs).restore(
            archive.data,
            tenants.b.id,
            tenants.b.owner_id,
            {str(tenants.a.owner_id): mapped_owner.id},
        )
    assert restore.status is OrganizationRestoreStatus.COMPLETED

    async with session_factory() as session:
        source_b = await session.scalar(
            select(Source).where(Source.organization_id == tenants.b.id)
        )
        assert source_b is not None and source_b.id != a.source_id
        document_b = await session.scalar(select(Document).where(Document.source_id == source_b.id))
        assert document_b is not None
        revision_b = await session.scalar(
            select(DocumentRevision).where(DocumentRevision.document_id == document_b.id)
        )
        assert revision_b is not None and revision_b.version == 1
        asset_b = await session.scalar(
            select(DocumentAsset).where(DocumentAsset.document_id == document_b.id)
        )
        assert asset_b is not None
        mention_entity = await session.scalar(
            select(EntityMention.entity_id).where(EntityMention.document_id == document_b.id)
        )
        claim_for_b = await session.scalar(
            select(ClaimEvidence.claim_id)
            .join(DocumentChunk, DocumentChunk.id == ClaimEvidence.chunk_id)
            .where(DocumentChunk.document_id == document_b.id)
        )
        cluster_b = await session.scalar(
            select(EventCluster).where(EventCluster.organization_id == tenants.b.id)
        )
        assert cluster_b is not None
        member_b = await session.scalar(
            select(func.count())
            .select_from(EventClusterMember)
            .where(EventClusterMember.cluster_id == cluster_b.id)
        )
        research_b = await session.scalar(
            select(ResearchSession).where(ResearchSession.organization_id == tenants.b.id)
        )
        assert research_b is not None and research_b.source_id == source_b.id
        turn_b = await session.scalar(
            select(func.count())
            .select_from(ResearchTurn)
            .where(ResearchTurn.session_id == research_b.id)
        )
        investigation_b = await session.scalar(
            select(Investigation).where(Investigation.organization_id == tenants.b.id)
        )
        assert investigation_b is not None
        item_b = await session.scalar(
            select(func.count())
            .select_from(InvestigationItem)
            .where(InvestigationItem.investigation_id == investigation_b.id)
        )
        owner_membership = await session.scalar(
            select(OrganizationMembership.role).where(
                OrganizationMembership.organization_id == tenants.b.id,
                OrganizationMembership.user_id == mapped_owner.id,
            )
        )
        invitations_b = await session.scalar(
            select(func.count())
            .select_from(OrganizationInvitation)
            .where(OrganizationInvitation.organization_id == tenants.b.id)
        )

    # Canonical entity and claim are shared, not duplicated.
    assert mention_entity == a.entity_id
    assert claim_for_b == a.claim_id
    # Relationships point at the restored records.
    assert member_b == 1
    assert turn_b == 1
    assert item_b == 1
    # The user mapping was applied, and the role was restored.
    assert owner_membership == "owner"
    assert investigation_b.created_by_user_id == mapped_owner.id
    # The binary asset is restored with matching content and checksum.
    assert restore_blobs.values[asset_b.storage_key] == ASSET_BYTES
    assert hashlib.sha256(restore_blobs.values[asset_b.storage_key]).hexdigest() == a.asset_sha256

    # Organization A is unchanged, and nothing leaks across tenants.
    assert await count(session_factory, Source) == sources_a_before
    async with session_factory() as session:
        source_a = await session.get(Source, a.source_id)
    assert source_a is not None and source_a.organization_id == tenants.a.id

    # Credentials, sessions, login throttle and invitations are never restored.
    assert await count(session_factory, UserPasswordCredential) == credentials_before
    assert await count(session_factory, UserSession) == sessions_before
    assert await count(session_factory, AuthenticationThrottle) == throttles_before
    assert invitations_b == 0
