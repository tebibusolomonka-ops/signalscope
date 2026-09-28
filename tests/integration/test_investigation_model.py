import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.investigations.model import Investigation, InvestigationStatus

pytestmark = pytest.mark.anyio


async def test_defaults_and_timestamps(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        investigation = Investigation(title="Harbour floods")
        session.add(investigation)
        await session.commit()

    async with session_factory() as session:
        stored = await session.get(Investigation, investigation.id)
    assert stored is not None
    assert (stored.title, stored.description, stored.status) == (
        "Harbour floods",
        None,
        InvestigationStatus.OPEN,
    )
    assert stored.created_at is not None and stored.updated_at is not None


async def test_closed_with_description(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        investigation = Investigation(
            title="Energy prices", description="Notes.", status=InvestigationStatus.CLOSED
        )
        session.add(investigation)
        await session.commit()
        stored = await session.get(Investigation, investigation.id)
    assert stored is not None
    assert (stored.description, stored.status) == ("Notes.", InvestigationStatus.CLOSED)


async def test_blank_title_is_rejected(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        session.add(Investigation(title="  "))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_unknown_status_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO investigations (id, title, status) "
                    "VALUES (gen_random_uuid(), 'x', 'archived')"
                )
            )
