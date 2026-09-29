import dataclasses
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from fake_reranker import FakeReranker
from password_helpers import fast_hasher
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.search.embedding_repository import ChunkEmbeddingRepository
from tenancy_helpers import Tenants, add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio

E5 = ("sentence_transformers", "intfloat/multilingual-e5-small")
A_TEXT = "Water levels rose near the harbour."
# Closer to the query "water" than A's text, so B would win if it were searched.
B_TEXT = "Water water water, said the bravo notice."
SEMANTIC = f"provider={E5[0]}&model={E5[1]}"


@pytest.fixture
def embedder() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider(*E5)


@pytest.fixture
def reranker() -> FakeReranker:
    return FakeReranker("sentence_transformers", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")


@pytest.fixture
async def client(
    database_engine: AsyncEngine,
    migrated_database: Settings,
    embedder: FakeEmbeddingProvider,
    reranker: FakeReranker,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(dataclasses.replace(migrated_database, auth_enabled=True))
    app.state.password_hasher = fast_hasher()
    app.state.embedding_providers.register(embedder)
    app.state.rerankers.register(reranker)
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def embedded_document(
    session_factory: async_sessionmaker[AsyncSession],
    embedder: FakeEmbeddingProvider,
    source_id: uuid.UUID,
    title: str,
    texts: list[str],
) -> list[str]:
    _, chunk_ids = await add_document(session_factory, source_id, title, texts)
    async with session_factory() as session:
        for chunk_id in chunk_ids:
            chunk = await session.get_one(DocumentChunk, chunk_id)
            await ChunkEmbeddingRepository(session).save(
                chunk.id, *E5, chunk.text_hash, embedder.vector(chunk.text)
            )
        await session.commit()
    return [str(chunk_id) for chunk_id in chunk_ids]


@pytest.fixture
async def world(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    embedder: FakeEmbeddingProvider,
) -> tuple[Tenants, list[str]]:
    tenants = await make_tenants(client, session_factory)
    a_source = await add_source(session_factory, tenants.a.id)
    b_source = await add_source(session_factory, tenants.b.id)
    a_chunks = await embedded_document(
        session_factory, embedder, a_source, "a-doc", [A_TEXT, f"Second {A_TEXT}"]
    )
    await embedded_document(session_factory, embedder, b_source, "b-doc", [B_TEXT] * 60)
    return tenants, a_chunks


@pytest.mark.parametrize(
    "path", [f"/search/semantic?{SEMANTIC}", f"/search/hybrid?{SEMANTIC}", "/search/reranked?"]
)
async def test_each_mode_sees_one_organization(
    client: httpx.AsyncClient, world: tuple[Tenants, list[str]], path: str
) -> None:
    tenants, a_chunks = world
    a = tenants.a

    response = await client.get(f"{path}&q=water&limit=2&{a.query}", headers=a.headers["viewer"])

    assert response.status_code == 200, response.text
    assert sorted(item["chunk_id"] for item in response.json()["items"]) == sorted(a_chunks)
    assert "b-doc" not in response.text and "bravo" not in response.text


async def test_the_limit_is_filled_inside_the_organization(
    client: httpx.AsyncClient, world: tuple[Tenants, list[str]]
) -> None:
    tenants, _ = world
    b = tenants.b

    for path in (f"/search/semantic?{SEMANTIC}", f"/search/hybrid?{SEMANTIC}"):
        response = await client.get(
            f"{path}&q=harbour water&limit=50&{b.query}", headers=b.headers["member"]
        )
        items = response.json()["items"]
        assert len(items) == 50
        assert {item["title"] for item in items} == {"b-doc"}


async def test_reranker_only_reads_the_organization(
    client: httpx.AsyncClient, world: tuple[Tenants, list[str]], reranker: FakeReranker
) -> None:
    tenants, _ = world

    response = await client.get(
        f"/search/reranked?q=water&limit=5&{tenants.a.query}", headers=tenants.a.headers["owner"]
    )

    assert response.status_code == 200
    passages = [passage for _, texts in reranker.calls for passage in texts]
    assert passages and all("bravo" not in passage for passage in passages)


async def test_errors(client: httpx.AsyncClient, world: tuple[Tenants, list[str]]) -> None:
    tenants, _ = world
    path = f"/search/semantic?{SEMANTIC}&q=water"

    other = await client.get(f"{path}&{tenants.b.query}", headers=tenants.a.headers["owner"])
    missing = await client.get(path, headers=tenants.a.headers["owner"])
    legacy = await client.get(path, headers=tenants.system)

    assert (other.status_code, missing.status_code) == (404, 422)
    assert legacy.json()["items"] == []
