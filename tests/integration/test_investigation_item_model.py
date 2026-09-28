import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.investigations.item import InvestigationItem, InvestigationItemType
from signalscope.domain.investigations.model import Investigation

pytestmark = pytest.mark.anyio


async def create_investigation(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        investigation = Investigation(title="Harbour floods")
        session.add(investigation)
        await session.commit()
        return investigation.id


async def add_item(
    session_factory: async_sessionmaker[AsyncSession],
    investigation_id: uuid.UUID,
    reference_id: uuid.UUID,
    item_type: InvestigationItemType = InvestigationItemType.EVENT,
) -> InvestigationItem:
    async with session_factory() as session:
        item = InvestigationItem(
            investigation_id=investigation_id,
            item_type=item_type,
            reference_id=reference_id,
            label="Worth a look",
            snapshot={"title": "Harbour flood", "event_type": "flood"},
        )
        session.add(item)
        await session.commit()
        return item


async def test_item_keeps_its_snapshot(session_factory: async_sessionmaker[AsyncSession]) -> None:
    investigation_id = await create_investigation(session_factory)
    item = await add_item(session_factory, investigation_id, uuid.uuid4())

    async with session_factory() as session:
        stored = await session.get(InvestigationItem, item.id)
    assert stored is not None
    assert (stored.item_type, stored.label, stored.snapshot) == (
        InvestigationItemType.EVENT,
        "Worth a look",
        {"title": "Harbour flood", "event_type": "flood"},
    )
    assert stored.created_at is not None


async def test_same_reference_once_per_type(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    investigation_id = await create_investigation(session_factory)
    other = await create_investigation(session_factory)
    reference = uuid.uuid4()
    await add_item(session_factory, investigation_id, reference)
    # Another type or another investigation may hold the same ID.
    await add_item(session_factory, investigation_id, reference, InvestigationItemType.CLAIM)
    await add_item(session_factory, other, reference)

    with pytest.raises(IntegrityError):
        await add_item(session_factory, investigation_id, reference)


async def test_unknown_type_and_bad_snapshot_are_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    investigation_id = await create_investigation(session_factory)
    for values in ("'graph', '{}'::jsonb", "'event', '[]'::jsonb"):
        async with session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO investigation_items "
                        "(id, investigation_id, reference_id, item_type, snapshot) "
                        f"VALUES (gen_random_uuid(), :investigation, gen_random_uuid(), {values})"
                    ),
                    {"investigation": investigation_id},
                )


async def test_deleting_an_investigation_deletes_its_items(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    investigation_id = await create_investigation(session_factory)
    other = await create_investigation(session_factory)
    await add_item(session_factory, investigation_id, uuid.uuid4())
    kept = await add_item(session_factory, other, uuid.uuid4())

    async with session_factory() as session:
        await session.execute(delete(Investigation).where(Investigation.id == investigation_id))
        await session.commit()
        remaining = list(await session.scalars(select(InvestigationItem.id)))

    assert remaining == [kept.id]
