import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from fake_embeddings import FakeEmbeddingProvider
from signalscope.core.errors import NotFoundError, ServiceUnavailableError
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.events.suggestions import EventLinkSuggestion, EventLinkSuggestionService
from signalscope.embeddings.registry import EmbeddingProviderRegistry

pytestmark = pytest.mark.anyio

E5 = ("sentence_transformers", "intfloat/multilingual-e5-small")
MARCH_4 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)
# The fake model only counts these words, so similarity is predictable.
WORDS = ("harbour", "river", "bridge")


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider(*E5, words=WORDS)


@pytest.fixture
def providers(provider: FakeEmbeddingProvider) -> EmbeddingProviderRegistry:
    registry = EmbeddingProviderRegistry()
    registry.register(provider)
    return registry


async def suggest(
    session_factory: async_sessionmaker[AsyncSession],
    providers: EmbeddingProviderRegistry,
    event_id: uuid.UUID,
    limit: int = 10,
) -> list[EventLinkSuggestion]:
    async with session_factory() as session:
        return await EventLinkSuggestionService(session, providers).suggest(event_id, limit)


async def test_most_similar_first_and_same_type_only(
    session_factory: async_sessionmaker[AsyncSession], providers: EmbeddingProviderRegistry
) -> None:
    source = await create_source(session_factory, "Wire")
    target = await report_event(session_factory, source, "Harbour water rising")
    close = await report_event(session_factory, source, "Harbour flooded by the sea")
    far = await report_event(session_factory, source, "River bridge flooded")
    await report_event(session_factory, source, "Harbour fire", event_type="fire")

    found = await suggest(session_factory, providers, target)

    assert [item.candidate_event_id for item in found] == [close, far]
    assert found[0].title == "Harbour flooded by the sea"
    assert found[0].similarity > found[1].similarity
    assert found[0].cluster_id is None


async def test_date_window(
    session_factory: async_sessionmaker[AsyncSession], providers: EmbeddingProviderRegistry
) -> None:
    source = await create_source(session_factory, "Wire")
    target = await report_event(session_factory, source, "Harbour flood", occurred_at=MARCH_4)
    near = await report_event(
        session_factory, source, "Harbour flood", occurred_at=MARCH_4 + timedelta(days=3)
    )
    await report_event(
        session_factory, source, "Harbour flood", occurred_at=MARCH_4 + timedelta(days=30)
    )
    undated = await report_event(session_factory, source, "Harbour flood")

    found = await suggest(session_factory, providers, target)

    assert {item.candidate_event_id for item in found} == {near, undated}


async def test_undated_event_sees_every_date(
    session_factory: async_sessionmaker[AsyncSession], providers: EmbeddingProviderRegistry
) -> None:
    source = await create_source(session_factory, "Wire")
    target = await report_event(session_factory, source, "Harbour flood")
    for days in (0, 30, 300):
        await report_event(
            session_factory, source, "Harbour flood", occurred_at=MARCH_4 + timedelta(days=days)
        )

    assert len(await suggest(session_factory, providers, target)) == 3


async def test_limit(
    session_factory: async_sessionmaker[AsyncSession], providers: EmbeddingProviderRegistry
) -> None:
    source = await create_source(session_factory, "Wire")
    target = await report_event(session_factory, source, "Harbour flood")
    for number in range(4):
        await report_event(session_factory, source, f"Harbour flood {number}")

    assert len(await suggest(session_factory, providers, target, limit=2)) == 2


async def test_cluster_is_reported_and_membership_never_changes(
    session_factory: async_sessionmaker[AsyncSession], providers: EmbeddingProviderRegistry
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    target = await report_event(session_factory, wire, "Harbour flood")
    same = await report_event(session_factory, paper, "Harbour flood")
    other = await report_event(session_factory, paper, "Harbour flooded")
    await EventLinkingService(session_factory).link_unclustered()
    async with session_factory() as session:
        before = list(
            await session.execute(
                select(EventClusterMember.event_id, EventClusterMember.cluster_id)
            )
        )
        other_cluster = await session.scalar(
            select(EventClusterMember.cluster_id).where(EventClusterMember.event_id == other)
        )

    found = await suggest(session_factory, providers, target)

    # Events already in the target's cluster are not suggested.
    assert [item.candidate_event_id for item in found] == [other]
    assert found[0].cluster_id == other_cluster
    assert same not in {item.candidate_event_id for item in found}
    async with session_factory() as session:
        after = list(
            await session.execute(
                select(EventClusterMember.event_id, EventClusterMember.cluster_id)
            )
        )
        cluster_count = await session.scalar(select(func.count()).select_from(EventCluster))
    assert sorted(after) == sorted(before)
    assert cluster_count == 2


async def test_no_candidates_embeds_nothing(
    session_factory: async_sessionmaker[AsyncSession],
    providers: EmbeddingProviderRegistry,
    provider: FakeEmbeddingProvider,
) -> None:
    source = await create_source(session_factory, "Wire")
    target = await report_event(session_factory, source, "Harbour flood")

    assert await suggest(session_factory, providers, target) == []
    assert provider.calls == []


async def test_missing_provider(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory, "Wire")
    target = await report_event(session_factory, source, "Harbour flood")

    with pytest.raises(ServiceUnavailableError, match="not configured"):
        await suggest(session_factory, EmbeddingProviderRegistry(), target)


async def test_unknown_event(
    session_factory: async_sessionmaker[AsyncSession], providers: EmbeddingProviderRegistry
) -> None:
    with pytest.raises(NotFoundError):
        await suggest(session_factory, providers, uuid.uuid4())
