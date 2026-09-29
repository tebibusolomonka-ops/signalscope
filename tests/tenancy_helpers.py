"""Two organizations with one user per role, for organization content tests.

Test passwords and tokens only.
"""

import hashlib
import uuid
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.organizations.membership import OrganizationRole
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.sources.model import Source, SourceType

ROLES = ("owner", "admin", "member", "viewer")


@dataclass
class Tenant:
    id: uuid.UUID
    # Bearer headers of this organization's users, by role.
    headers: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def query(self) -> str:
        return f"organization_id={self.id}"


@dataclass
class Tenants:
    a: Tenant
    b: Tenant
    system: dict[str, str]
    outsider: dict[str, str]


async def make_tenants(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> Tenants:
    """Organizations A and B, each with an owner, admin, member and viewer.

    Also a system admin and a user in no organization.
    """
    tenants = []
    for name in ("a", "b"):
        users = {
            role: await create_account(session_factory, f"{name}-{role}@example.org")
            for role in ROLES
        }
        async with session_factory() as session:
            service = OrganizationService(session)
            organization = await service.create(users["owner"], f"Org {name}", f"org-{name}")
            for role in ROLES[1:]:
                await service.add_member(
                    users["owner"], organization.id, users[role].id, OrganizationRole(role)
                )
        tenant = Tenant(organization.id)
        for role in ROLES:
            tenant.headers[role] = bearer(await login(client, f"{name}-{role}@example.org"))
        tenants.append(tenant)
    await create_account(session_factory, "system@example.org", system_admin=True)
    await create_account(session_factory, "outsider@example.org")
    return Tenants(
        a=tenants[0],
        b=tenants[1],
        system=bearer(await login(client, "system@example.org")),
        outsider=bearer(await login(client, "outsider@example.org")),
    )


async def add_source(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID | None,
    name: str = "Harbour feed",
) -> uuid.UUID:
    async with session_factory() as session:
        source = Source(
            type=SourceType.RSS,
            name=name,
            url="https://example.org/feed.xml",
            organization_id=organization_id,
        )
        session.add(source)
        await session.commit()
        return source.id


async def add_document(
    session_factory: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    title: str,
    texts: list[str],
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """A document in the source with one chunk per text. Returns its ID and chunk IDs."""
    chunks = [
        TextChunk(
            position=index,
            text=text,
            start_char=0,
            end_char=len(text),
            text_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        for index, text in enumerate(texts)
    ]
    async with session_factory() as session:
        document = Document(source_id=source_id, title=title, url=f"https://example.org/{title}")
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        saved = await repository.list_by_document(document.id)
        await session.commit()
        return document.id, [chunk.id for chunk in saved]


async def add_findings(
    session_factory: async_sessionmaker[AsyncSession],
    chunk_id: uuid.UUID,
    entity_name: str = "Porto",
    claim_text: str = "Water rose",
) -> tuple[uuid.UUID, uuid.UUID]:
    """A mention of the entity and evidence for the claim in one chunk.

    The entity and claim rows are shared: an existing one with the same name or
    text is reused, like the extraction workers do. Returns their IDs.
    """
    async with session_factory() as session:
        chunk = await session.get_one(DocumentChunk, chunk_id)
        entity = await session.scalar(
            select(Entity).where(Entity.normalized_name == entity_name.lower())
        )
        if entity is None:
            entity = Entity(
                canonical_name=entity_name, normalized_name=entity_name.lower(), entity_type="city"
            )
            session.add(entity)
        claim = await session.scalar(
            select(Claim).where(Claim.normalized_text == claim_text.lower())
        )
        if claim is None:
            claim = Claim(
                text=claim_text, normalized_text=claim_text.lower(), claim_type="statistic"
            )
            session.add(claim)
        await session.flush()
        session.add_all(
            [
                EntityMention(
                    entity_id=entity.id,
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    surface_text=chunk.text[:4],
                    entity_type="city",
                    start_char=0,
                    end_char=4,
                    provider="test",
                    model="m",
                    chunk_text_hash=chunk.text_hash,
                ),
                ClaimEvidence(
                    claim_id=claim.id,
                    chunk_id=chunk.id,
                    surface_text=chunk.text[:4],
                    start_char=0,
                    end_char=4,
                    provider="test",
                    model="m",
                ),
            ]
        )
        await session.commit()
        return entity.id, claim.id
