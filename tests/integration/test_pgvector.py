import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.anyio


async def test_vector_extension_is_installed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        version = await session.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )

    assert version is not None


async def test_vectors_can_be_read_and_compared(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        stored = await session.scalar(text("SELECT '[1,2,3]'::vector"))
        # 0 means the same direction, so cosine distance works.
        distance = await session.scalar(text("SELECT '[1,0,0]'::vector <=> '[2,0,0]'::vector"))
        dimensions = await session.scalar(text("SELECT vector_dims('[1,2,3,4]'::vector)"))

    assert str(stored).replace(" ", "") == "[1,2,3]"
    assert distance == pytest.approx(0)
    assert dimensions == 4


async def test_vectors_of_different_sizes_cannot_be_compared(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(Exception, match="different vector dimensions"):
            await session.scalar(text("SELECT '[1,2]'::vector <=> '[1,2,3]'::vector"))
