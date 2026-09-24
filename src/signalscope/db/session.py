from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # Keep loaded values after commit. Async sessions cannot reload expired
    # attributes when they are accessed.
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a new session and close it when the caller is done.

    The caller decides when to commit. Closing rolls back anything that was
    not committed, also when the caller raises an error.
    """
    async with session_factory() as session:
        yield session
