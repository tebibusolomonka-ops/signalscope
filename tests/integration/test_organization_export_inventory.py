import hashlib
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.organizations.export_inventory import OrganizationExportInventoryService
from signalscope.domain.sources.model import Source, SourceType
from tenancy_helpers import make_tenants

pytestmark = pytest.mark.anyio


async def add_evidence(
    session: AsyncSession,
    organization_id: uuid.UUID | None,
    suffix: str,
    entity: Entity,
    claim: Claim,
) -> tuple[Source, Document, EntityMention, ClaimEvidence]:
    source = Source(
        type=SourceType.WEB,
        name=f"Source {suffix}",
        url=f"https://example.com/{suffix}",
        organization_id=organization_id,
    )
    session.add(source)
    await session.flush()
    text = f"Jordan reported claim {suffix}."
    document = Document(source_id=source.id, title=f"Document {suffix}", content=text)
    session.add(document)
    await session.flush()
    text_hash = hashlib.sha256(text.encode()).hexdigest()
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
    mention = EntityMention(
        entity_id=entity.id,
        document_id=document.id,
        chunk_id=chunk.id,
        surface_text="Jordan",
        entity_type="person",
        start_char=0,
        end_char=6,
        confidence=0.9,
        provider="test",
        model="test",
        chunk_text_hash=text_hash,
    )
    evidence = ClaimEvidence(
        claim_id=claim.id,
        chunk_id=chunk.id,
        surface_text="reported claim",
        start_char=7,
        end_char=21,
        confidence=0.8,
        provider="test",
        model="test",
    )
    session.add_all([mention, evidence])
    return source, document, mention, evidence


async def test_inventory_is_complete_scoped_and_keeps_shared_identity(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    async with session_factory() as session:
        entity = Entity(canonical_name="Jordan", normalized_name="jordan", entity_type="person")
        claim = Claim(text="A shared claim", normalized_text="a shared claim", claim_type="fact")
        session.add_all([entity, claim])
        await session.flush()
        own = await add_evidence(session, tenants.a.id, "a", entity, claim)
        other = await add_evidence(session, tenants.b.id, "b", entity, claim)
        legacy = await add_evidence(session, None, "legacy", entity, claim)
        await session.commit()

    async with session_factory() as session:
        inventory = await OrganizationExportInventoryService(session).build(tenants.a.id)

    assert inventory.organization[0].id == tenants.a.id
    assert [item.id for item in inventory.sources] == [own[0].id]
    assert [item.id for item in inventory.documents] == [own[1].id]
    assert [item.id for item in inventory.entities] == [entity.id]
    assert [item.id for item in inventory.claims] == [claim.id]
    assert [item.id for item in inventory.entity_mentions] == [own[2].id]
    assert [item.id for item in inventory.claim_evidence] == [own[3].id]
    excluded = {other[0].id, other[1].id, legacy[0].id, legacy[1].id}
    exported = {item.id for item in inventory.sources + inventory.documents}
    assert exported.isdisjoint(excluded)
