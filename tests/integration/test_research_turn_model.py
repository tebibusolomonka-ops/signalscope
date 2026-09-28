import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.research.session import ResearchSession
from signalscope.domain.research.turn import ResearchTurn

pytestmark = pytest.mark.anyio

SNAPSHOT = [
    {
        "evidence_id": "E1",
        "document_id": str(uuid.uuid4()),
        "title": "Harbour Report",
        "excerpt": "Water flooded the harbour.",
        "chunk_metadata": {"page_number": 2},
    }
]


async def create_session(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        research = ResearchSession()
        session.add(research)
        await session.commit()
        return research.id


async def add_turn(
    session_factory: async_sessionmaker[AsyncSession], session_id: uuid.UUID, sequence: int
) -> ResearchTurn:
    async with session_factory() as session:
        turn = ResearchTurn(
            session_id=session_id,
            sequence=sequence,
            question="What flooded?",
            answer="The harbour flooded [E1].",
            citation_ids=["E1"],
            evidence_snapshot=SNAPSHOT,
        )
        session.add(turn)
        await session.commit()
        return turn


async def test_turn_keeps_its_snapshot(session_factory: async_sessionmaker[AsyncSession]) -> None:
    session_id = await create_session(session_factory)
    turn = await add_turn(session_factory, session_id, 1)

    async with session_factory() as session:
        stored = await session.get(ResearchTurn, turn.id)
    assert stored is not None
    assert (stored.sequence, stored.citation_ids, stored.evidence_snapshot) == (1, ["E1"], SNAPSHOT)
    assert stored.created_at is not None


async def test_defaults(session_factory: async_sessionmaker[AsyncSession]) -> None:
    session_id = await create_session(session_factory)
    async with session_factory() as session:
        turn = ResearchTurn(session_id=session_id, sequence=1, question="Anything?")
        session.add(turn)
        await session.commit()
        stored = await session.get(ResearchTurn, turn.id)
    assert stored is not None
    assert (stored.answer, stored.citation_ids, stored.evidence_snapshot) == (None, [], [])


async def test_sequence_is_unique_in_a_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first, second = await create_session(session_factory), await create_session(session_factory)
    await add_turn(session_factory, first, 1)
    await add_turn(session_factory, second, 1)

    with pytest.raises(IntegrityError):
        await add_turn(session_factory, first, 1)


@pytest.mark.parametrize(
    "values",
    [
        {"sequence": 0},
        {"question": "  "},
        {"citation_ids": {"E1": True}},
        {"evidence_snapshot": "E1"},
    ],
    ids=["sequence zero", "blank question", "citations not a list", "snapshot not a list"],
)
async def test_bad_values_are_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, object]
) -> None:
    session_id = await create_session(session_factory)
    fields: dict[str, object] = {"session_id": session_id, "sequence": 1, "question": "Why?"}
    async with session_factory() as session:
        session.add(ResearchTurn(**(fields | values)))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_deleting_a_session_deletes_its_turns(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    session_id = await create_session(session_factory)
    other = await create_session(session_factory)
    await add_turn(session_factory, session_id, 1)
    await add_turn(session_factory, session_id, 2)
    kept = await add_turn(session_factory, other, 1)

    async with session_factory() as session:
        await session.execute(delete(ResearchSession).where(ResearchSession.id == session_id))
        await session.commit()
        remaining = list(await session.scalars(select(ResearchTurn.id)))

    assert remaining == [kept.id]
