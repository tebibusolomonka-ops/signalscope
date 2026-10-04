import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.claims.model import ClaimEvidence
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.investigations.item import InvestigationItem, InvestigationItemType
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.organizations.drill_record import (
    DisasterRecoveryDrillMode,
    DisasterRecoveryDrillStatus,
)
from signalscope.domain.organizations.drill_service import (
    OrganizationDisasterRecoveryDrillService,
)
from signalscope.domain.organizations.invitation import InvitationRole, OrganizationInvitation
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.research.turn import ResearchTurn
from signalscope.domain.sources.model import Source
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.session import UserSession
from signalscope.domain.users.throttle import AuthenticationThrottle
from tenancy_helpers import add_document, add_findings, add_source, make_tenants

pytestmark = pytest.mark.anyio

ASSET = b"disaster recovery drill asset bytes"


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


async def build_rich_org(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID,
    owner_id: uuid.UUID,
    blobs: MemoryBlobs,
) -> str:
    source_id = await add_source(session_factory, organization_id, "DR source")
    document_id, chunk_ids = await add_document(
        session_factory, source_id, "DR doc", ["Harbour flooded after the storm."]
    )
    await add_findings(session_factory, chunk_ids[0])
    asset_sha = hashlib.sha256(ASSET).hexdigest()
    async with session_factory() as session:
        asset = DocumentAsset(
            document_id=document_id,
            storage_key=f"document-assets/{uuid.uuid4()}",
            filename="evidence.bin",
            content_type="application/octet-stream",
            size_bytes=len(ASSET),
            sha256=asset_sha,
        )
        event = Event(event_type="flood", title="DR flood")
        cluster = EventCluster(
            event_type="flood",
            canonical_title="DR flood",
            normalized_title="dr flood",
            organization_id=organization_id,
        )
        session.add_all([asset, event, cluster])
        await session.flush()
        session.add(
            EventEvidence(event_id=event.id, chunk_id=chunk_ids[0], provider="t", model="m")
        )
        session.add(EventClusterMember(event_id=event.id, cluster_id=cluster.id))
        research = ResearchSession(
            title="DR questions", source_id=source_id, organization_id=organization_id
        )
        investigation = Investigation(
            title="DR investigation", organization_id=organization_id, created_by_user_id=owner_id
        )
        session.add_all([research, investigation])
        await session.flush()
        session.add(ResearchTurn(session_id=research.id, sequence=1, question="What happened?"))
        session.add(
            InvestigationItem(
                investigation_id=investigation.id,
                item_type=InvestigationItemType.SOURCE,
                reference_id=source_id,
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
        blobs.values[asset.storage_key] = ASSET
    return asset_sha


async def count_where(
    session_factory: async_sessionmaker[AsyncSession], model: type, condition: object
) -> int:
    async with session_factory() as session:
        value = await session.scalar(select(func.count()).select_from(model).where(condition))
    return value or 0


async def total(session_factory: async_sessionmaker[AsyncSession], model: type) -> int:
    async with session_factory() as session:
        value = await session.scalar(select(func.count()).select_from(model))
    return value or 0


async def test_disaster_recovery_drills_end_to_end(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    blobs = MemoryBlobs()
    asset_sha = await build_rich_org(session_factory, tenants.a.id, tenants.a.owner_id, blobs)

    async with session_factory() as session:
        session.add(
            AuthenticationThrottle(
                identifier="b" * 64, failure_count=1, window_started_at=datetime.now(UTC)
            )
        )
        await session.commit()

    credentials_before = await total(session_factory, UserPasswordCredential)
    sessions_before = await total(session_factory, UserSession)
    throttles_before = await total(session_factory, AuthenticationThrottle)
    a_sources_before = await count_where(
        session_factory, Source, Source.organization_id == tenants.a.id
    )

    # Verification-only drill changes nothing.
    async with session_factory() as session:
        verification = await OrganizationDisasterRecoveryDrillService(session, blobs).run(
            tenants.a.id, tenants.a.owner_id, mode=DisasterRecoveryDrillMode.VERIFICATION_ONLY
        )
    assert verification.status is DisasterRecoveryDrillStatus.COMPLETED
    assert verification.summary["plan_conflicts"] == []
    assert verification.summary["counts"]["sources"] == 1
    assert await count_where(session_factory, Source, Source.organization_id == tenants.b.id) == 0

    # Restore-test drill restores into the empty target organization B.
    async with session_factory() as session:
        restore_test = await OrganizationDisasterRecoveryDrillService(session, blobs).run(
            tenants.a.id,
            tenants.a.owner_id,
            mode=DisasterRecoveryDrillMode.RESTORE_TEST,
            target_organization_id=tenants.b.id,
        )
    assert restore_test.status is DisasterRecoveryDrillStatus.COMPLETED
    assert restore_test.restore_id is not None

    async with session_factory() as session:
        source_b = await session.scalar(
            select(Source).where(Source.organization_id == tenants.b.id)
        )
        assert source_b is not None
        asset_b = await session.scalar(
            select(DocumentAsset).where(
                DocumentAsset.storage_key.startswith(f"document-assets/{tenants.b.id}/")
            )
        )
        research_b = await session.scalar(
            select(func.count())
            .select_from(ResearchSession)
            .where(ResearchSession.organization_id == tenants.b.id)
        )
        investigations_b = await session.scalar(
            select(func.count())
            .select_from(Investigation)
            .where(Investigation.organization_id == tenants.b.id)
        )
        document_b = await session.scalar(
            select(Document.id).where(Document.source_id == source_b.id)
        )
        entity_mentions_b = await session.scalar(
            select(func.count())
            .select_from(EntityMention)
            .where(EntityMention.document_id == document_b)
        )
        claim_evidence_total = await session.scalar(select(func.count()).select_from(ClaimEvidence))

    assert asset_b is not None
    assert blobs.values[asset_b.storage_key] == ASSET
    assert hashlib.sha256(blobs.values[asset_b.storage_key]).hexdigest() == asset_sha
    assert research_b == 1
    assert investigations_b == 1
    assert entity_mentions_b and entity_mentions_b >= 1
    assert claim_evidence_total >= 2  # original plus restored evidence

    # Source organization A is unchanged.
    assert (
        await count_where(session_factory, Source, Source.organization_id == tenants.a.id)
        == a_sources_before
    )

    # No credentials, sessions, throttles were restored, and B has no invitations.
    assert await total(session_factory, UserPasswordCredential) == credentials_before
    assert await total(session_factory, UserSession) == sessions_before
    assert await total(session_factory, AuthenticationThrottle) == throttles_before
    assert (
        await count_where(
            session_factory,
            OrganizationInvitation,
            OrganizationInvitation.organization_id == tenants.b.id,
        )
        == 0
    )
