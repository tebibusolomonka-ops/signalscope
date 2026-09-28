import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.domain.claims.model import Claim
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.investigations.item import InvestigationItem, InvestigationItemType
from signalscope.domain.investigations.model import InvestigationStatus
from signalscope.domain.investigations.service import InvestigationService
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.sources.model import Source
from signalscope.research.evidence import ResearchMode

pytestmark = pytest.mark.anyio

MARCH_4 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


async def records(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID]:
    """One record of every type an investigation can save."""
    source = await create_source(session_factory, "Wire")
    event = await report_event(session_factory, source, "Harbour flood", occurred_at=MARCH_4)
    link = await EventLinkingService(session_factory).link_event(event)
    assert link is not None
    async with session_factory() as session:
        document = await session.scalar(select(Document.id).where(Document.source_id == source))
        entity = Entity(canonical_name="Porto", normalized_name="porto", entity_type="city")
        claim = Claim(
            text="Prices rose 5%", normalized_text="prices rose 5%", claim_type="statistic"
        )
        research = ResearchSession(title="Floods", retrieval_mode=ResearchMode.LEXICAL)
        session.add_all([entity, claim, research])
        await session.commit()
    assert document is not None
    return {
        "source": source,
        "document": document,
        "event": event,
        "event_cluster": link.cluster_id,
        "entity": entity.id,
        "claim": claim.id,
        "research_session": research.id,
    }


async def create(
    session_factory: async_sessionmaker[AsyncSession], title: str = "Floods"
) -> uuid.UUID:
    async with session_factory() as session:
        return (await InvestigationService(session).create(title, "Harbour notes")).id


async def test_create_get_update_and_list(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await create(session_factory, "Floods")
    second = await create(session_factory, "Prices")

    async with session_factory() as session:
        service = InvestigationService(session)
        updated = await service.update(first, title="Harbour floods", clear_description=True)
        await service.close(second)
        everything, total = await service.list_page(None, 50, 0)
        closed, closed_total = await service.list_page(InvestigationStatus.CLOSED, 50, 0)
        found = await service.get(first)

    assert (updated.title, updated.description) == ("Harbour floods", None)
    assert (found.title, found.status) == ("Harbour floods", InvestigationStatus.OPEN)
    # Newest first.
    assert ([item.id for item in everything], total) == ([second, first], 2)
    assert ([item.id for item in closed], closed_total) == ([second], 1)


async def test_close_and_reopen(session_factory: async_sessionmaker[AsyncSession]) -> None:
    investigation_id = await create(session_factory)
    source = await create_source(session_factory, "Wire")

    async with session_factory() as session:
        service = InvestigationService(session)
        await service.close(investigation_id)
        for change in (
            service.update(investigation_id, title="New title"),
            service.add_item(investigation_id, InvestigationItemType.SOURCE, source),
            service.delete(investigation_id),
        ):
            with pytest.raises(ConflictError, match="closed"):
                await change
        # Reopening and editing in one call is allowed.
        reopened = await service.update(
            investigation_id, status=InvestigationStatus.OPEN, title="New title"
        )
        item = await service.add_item(investigation_id, InvestigationItemType.SOURCE, source)

    assert (reopened.status, reopened.title) == (InvestigationStatus.OPEN, "New title")
    assert item.snapshot["name"] == "Wire"


async def test_every_item_type_gets_a_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    saved = await records(session_factory)
    investigation_id = await create(session_factory)

    async with session_factory() as session:
        service = InvestigationService(session)
        for item_type in InvestigationItemType:
            await service.add_item(investigation_id, item_type, saved[item_type.value], "note")
        items = await service.list_items(investigation_id)

    snapshots = {item.item_type.value: item.snapshot for item in items}
    assert [item.item_type for item in items] == list(InvestigationItemType)
    assert snapshots["source"] == {"name": "Wire", "source_type": "upload", "url": None}
    assert snapshots["document"]["title"] == "Harbour flood"
    assert snapshots["document"]["source_id"] == str(saved["source"])
    assert snapshots["event"] == {
        "event_type": "flood",
        "title": "Harbour flood",
        "occurred_at": MARCH_4.isoformat(),
    }
    assert snapshots["event_cluster"]["title"] == "Harbour flood"
    assert snapshots["entity"] == {"canonical_name": "Porto", "entity_type": "city"}
    assert snapshots["claim"] == {"text": "Prices rose 5%", "claim_type": "statistic"}
    assert snapshots["research_session"] == {
        "title": "Floods",
        "retrieval_mode": "lexical",
        "source_id": None,
        "turn_count": 0,
        "latest_turn_at": None,
    }
    assert all(item.label == "note" for item in items)
    # Snapshots stay small: no document content.
    assert all("content" not in snapshot for snapshot in snapshots.values())


async def test_duplicate_and_unknown_references(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, "Wire")
    investigation_id = await create(session_factory)

    async with session_factory() as session:
        service = InvestigationService(session)
        await service.add_item(investigation_id, InvestigationItemType.SOURCE, source)
        with pytest.raises(ConflictError, match="already saved"):
            await service.add_item(investigation_id, InvestigationItemType.SOURCE, source)
        with pytest.raises(NotFoundError, match="event cluster to save"):
            await service.add_item(investigation_id, InvestigationItemType.EVENT_CLUSTER, source)
        with pytest.raises(NotFoundError, match="Investigation"):
            await service.add_item(uuid.uuid4(), InvestigationItemType.SOURCE, source)
        assert len(await service.list_items(investigation_id)) == 1


async def test_remove_item(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory, "Wire")
    investigation_id = await create(session_factory)
    other = await create(session_factory)

    async with session_factory() as session:
        service = InvestigationService(session)
        item = await service.add_item(investigation_id, InvestigationItemType.SOURCE, source)
        with pytest.raises(NotFoundError):
            await service.remove_item(other, item.id)
        await service.remove_item(investigation_id, item.id)
        assert await service.list_items(investigation_id) == []


async def test_delete_removes_items_but_not_records(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, "Wire")
    investigation_id = await create(session_factory)

    async with session_factory() as session:
        service = InvestigationService(session)
        await service.add_item(investigation_id, InvestigationItemType.SOURCE, source)
        await service.delete(investigation_id)
        with pytest.raises(NotFoundError):
            await service.get(investigation_id)
        assert list(await session.scalars(select(InvestigationItem))) == []
        assert await session.get(Source, source) is not None
