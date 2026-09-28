import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from fake_embeddings import FakeEmbeddingProvider
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.events.model import Event
from signalscope.embeddings.registry import EmbeddingProviderRegistry

pytestmark = pytest.mark.anyio

E5 = ("sentence_transformers", "intfloat/multilingual-e5-small")
MARCH_4 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


@pytest.fixture
async def embedding_client(migrated_database: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_database)
    registry = EmbeddingProviderRegistry()
    # The fake only counts these words, so similarity is predictable.
    registry.register(FakeEmbeddingProvider(*E5, words=("harbour", "river", "bridge")))
    app.state.embedding_providers = registry
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def suggestions(
    client: httpx.AsyncClient, event_id: uuid.UUID, **params: Any
) -> list[dict[str, Any]]:
    response = await client.get(f"/events/{event_id}/link-suggestions", params=params)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


async def snapshot(session_factory: async_sessionmaker[AsyncSession]) -> tuple[Any, ...]:
    async with session_factory() as session:
        events = sorted(await session.execute(select(Event.id, Event.title, Event.updated_at)))
        members = sorted(
            await session.execute(
                select(EventClusterMember.event_id, EventClusterMember.cluster_id)
            )
        )
        clusters = await session.scalar(select(func.count()).select_from(EventCluster))
    return tuple(events), tuple(members), clusters


async def test_ranked_suggestions_change_nothing(
    embedding_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    target = await report_event(session_factory, wire, "Harbour water rising")
    close = await report_event(session_factory, paper, "Harbour flooded by the sea")
    far = await report_event(session_factory, paper, "River bridge flooded")
    await report_event(session_factory, paper, "Harbour fire", event_type="fire")
    await EventLinkingService(session_factory).link_unclustered()
    before = await snapshot(session_factory)

    found = await suggestions(embedding_client, target)

    assert [item["candidate_event_id"] for item in found] == [str(close), str(far)]
    assert found[0]["title"] == "Harbour flooded by the sea"
    assert found[0]["candidate_cluster_id"] is not None
    assert found[0]["similarity"] > found[1]["similarity"]
    assert await snapshot(session_factory) == before


async def test_limit_and_date_window(
    embedding_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await create_source(session_factory, "Wire")
    target = await report_event(session_factory, source, "Harbour flood", occurred_at=MARCH_4)
    near = await report_event(
        session_factory, source, "Harbour flooded", occurred_at=MARCH_4 + timedelta(days=2)
    )
    await report_event(
        session_factory, source, "Harbour flooded", occurred_at=MARCH_4 + timedelta(days=60)
    )
    undated = await report_event(session_factory, source, "Harbour flooded")

    everything = await suggestions(embedding_client, target)
    one = await suggestions(embedding_client, target, limit=1)

    assert {item["candidate_event_id"] for item in everything} == {str(near), str(undated)}
    assert len(one) == 1


async def test_unknown_event(embedding_client: httpx.AsyncClient) -> None:
    response = await embedding_client.get(f"/events/{uuid.uuid4()}/link-suggestions")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Event was not found."


async def test_no_embedding_provider(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await create_source(session_factory, "Wire")
    target = await report_event(session_factory, source, "Harbour flood")

    response = await client.get(f"/events/{target}/link-suggestions")

    assert response.status_code == 503
