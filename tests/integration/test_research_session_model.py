import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source
from signalscope.core.errors import ConflictError
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.sources.service import SourceService
from signalscope.research.evidence import ResearchMode

pytestmark = pytest.mark.anyio


async def test_defaults_and_timestamps(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        research = ResearchSession()
        session.add(research)
        await session.commit()

    async with session_factory() as session:
        stored = await session.get(ResearchSession, research.id)
    assert stored is not None
    assert (stored.title, stored.retrieval_mode, stored.source_id) == (
        None,
        ResearchMode.HYBRID,
        None,
    )
    assert stored.created_at is not None and stored.updated_at is not None


async def test_mode_and_source(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source_id = await create_source(session_factory, "Wire")
    async with session_factory() as session:
        research = ResearchSession(
            title="Harbour floods", retrieval_mode=ResearchMode.LEXICAL, source_id=source_id
        )
        session.add(research)
        await session.commit()

    async with session_factory() as session:
        stored = await session.get(ResearchSession, research.id)
    assert stored is not None
    assert (stored.retrieval_mode, stored.source_id) == (ResearchMode.LEXICAL, source_id)


async def test_unknown_mode_is_rejected(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO research_sessions (id, retrieval_mode) "
                    "VALUES (gen_random_uuid(), 'fuzzy')"
                )
            )


async def test_source_must_exist_and_cannot_be_deleted_while_used(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(ResearchSession(source_id=uuid.uuid4()))
        with pytest.raises(IntegrityError):
            await session.commit()

    source_id = await create_source(session_factory, "Wire")
    async with session_factory() as session:
        session.add(ResearchSession(source_id=source_id))
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(ConflictError, match="research sessions"):
            await SourceService(session).delete(source_id)
