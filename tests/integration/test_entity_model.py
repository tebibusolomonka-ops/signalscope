from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.entities.model import Entity
from signalscope.domain.entities.names import normalize_entity_name

pytestmark = pytest.mark.anyio


def entity(name: str, entity_type: str = "person", **values: Any) -> Entity:
    fields: dict[str, Any] = {
        "canonical_name": name,
        "normalized_name": normalize_entity_name(name),
        "entity_type": entity_type,
    }
    return Entity(**(fields | values))


async def test_entity_is_stored(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        session.add(entity("Angela Merkel"))
        await session.commit()

    async with session_factory() as session:
        [saved] = await session.scalars(select(Entity))
    assert (saved.canonical_name, saved.normalized_name, saved.entity_type) == (
        "Angela Merkel",
        "angela merkel",
        "person",
    )
    assert saved.created_at is not None


async def test_one_entity_per_normalized_name_and_type(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(entity("Angela Merkel"))
        await session.commit()

    async with session_factory() as session:
        session.add(entity("ANGELA  MERKEL"))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_same_name_with_another_type_is_another_entity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all([entity("Jordan", "person"), entity("Jordan", "location")])
        await session.commit()

    async with session_factory() as session:
        assert len(list(await session.scalars(select(Entity)))) == 2


@pytest.mark.parametrize(
    "values",
    [{"canonical_name": "  "}, {"normalized_name": ""}, {"entity_type": " "}],
    ids=["blank name", "blank normalized name", "blank type"],
)
async def test_blank_values_are_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, str]
) -> None:
    async with session_factory() as session:
        session.add(entity("Angela Merkel", **values))
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.parametrize(
    "values",
    [{"canonical_name": "x" * 301}, {"entity_type": "t" * 51}],
    ids=["long name", "long type"],
)
async def test_field_limits(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, str]
) -> None:
    async with session_factory() as session:
        session.add(entity("Angela Merkel", **values))
        with pytest.raises(DBAPIError):
            await session.flush()
