from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.core.settings import Settings
from signalscope.db.engine import create_database_engine
from signalscope.db.session import create_session_factory, get_session

# The .invalid domain never resolves, so any connection attempt would fail.
DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_database_engine(Settings(database_url=DATABASE_URL))
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.mark.anyio
async def test_factory_creates_sessions_bound_to_engine(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    assert isinstance(session_factory, async_sessionmaker)

    async with session_factory() as session:
        assert isinstance(session, AsyncSession)
        assert session.bind is engine


@pytest.mark.anyio
async def test_sessions_do_not_expire_values_on_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        assert session.sync_session.expire_on_commit is False


@pytest.mark.anyio
async def test_get_session_closes_session_when_done(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    sessions = get_session(session_factory)

    session = await anext(sessions)
    assert isinstance(session, AsyncSession)
    assert session.bind is engine
    await session.begin()
    assert session.in_transaction()

    with pytest.raises(StopAsyncIteration):
        await anext(sessions)

    assert not session.in_transaction()


@pytest.mark.anyio
async def test_get_session_closes_session_when_caller_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sessions = get_session(session_factory)
    session = await anext(sessions)
    await session.begin()

    with pytest.raises(RuntimeError, match="request failed"):
        await sessions.athrow(RuntimeError("request failed"))

    assert not session.in_transaction()
