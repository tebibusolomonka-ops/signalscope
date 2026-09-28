import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from fake_answers import FakeAnswerGenerator
from signalscope.core.errors import NotFoundError, ServiceUnavailableError
from signalscope.domain.research.service import MAX_HISTORY_TURNS, ResearchSessionService
from signalscope.domain.research.turn import ResearchTurn
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.reranking.registry import RerankerRegistry
from signalscope.research.evidence import ResearchMode
from signalscope.research.generation import AnswerGeneratorRegistry

pytestmark = pytest.mark.anyio


def service(
    session: AsyncSession, generator: FakeAnswerGenerator | None = None
) -> ResearchSessionService:
    generators = AnswerGeneratorRegistry()
    if generator is not None:
        generators.register(generator)
    return ResearchSessionService(
        session, EmbeddingProviderRegistry(), RerankerRegistry(), generators
    )


async def new_session(
    session_factory: async_sessionmaker[AsyncSession], **options: object
) -> uuid.UUID:
    options = {"retrieval_mode": ResearchMode.LEXICAL} | options
    async with session_factory() as session:
        research = await service(session).create_session(**options)  # type: ignore[arg-type]
        return research.id


async def ask(
    session_factory: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
    question: str,
    generator: FakeAnswerGenerator | None = None,
) -> ResearchTurn:
    async with session_factory() as session:
        return await service(session, generator).add_turn(session_id, question)


@pytest.fixture
async def library(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID]:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    await report_event(session_factory, wire, "Harbour flood")
    await report_event(session_factory, paper, "Harbour flood warning")
    return {"wire": wire, "paper": paper}


async def test_create_and_get(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory, "Wire")
    async with session_factory() as session:
        created = await service(session).create_session(
            title="Floods", retrieval_mode=ResearchMode.SEMANTIC, source_id=source
        )
    async with session_factory() as session:
        found = await service(session).get_session(created.id)

    assert (found.title, found.retrieval_mode, found.source_id) == (
        "Floods",
        ResearchMode.SEMANTIC,
        source,
    )


async def test_unknown_session_and_source(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Research session"):
            await service(session).get_session(uuid.uuid4())
        with pytest.raises(NotFoundError, match="Research session"):
            await service(session).add_turn(uuid.uuid4(), "harbour")
        with pytest.raises(NotFoundError, match="Source"):
            await service(session).create_session(source_id=uuid.uuid4())


async def test_without_a_generator_turns_keep_their_evidence(
    session_factory: async_sessionmaker[AsyncSession], library: dict[str, uuid.UUID]
) -> None:
    session_id = await new_session(session_factory)

    turn = await ask(session_factory, session_id, "harbour flood")

    assert (turn.sequence, turn.answer, turn.citation_ids) == (1, None, [])
    assert [item["evidence_id"] for item in turn.evidence_snapshot] == ["E1", "E2"]
    first = turn.evidence_snapshot[0]
    assert set(first) == {
        "evidence_id",
        "document_id",
        "chunk_id",
        "source_id",
        "title",
        "url",
        "excerpt",
        "text",
        "chunk_metadata",
    }


async def test_generator_answer_and_citations_are_saved(
    session_factory: async_sessionmaker[AsyncSession], library: dict[str, uuid.UUID]
) -> None:
    session_id = await new_session(session_factory)
    generator = FakeAnswerGenerator()

    turn = await ask(session_factory, session_id, "harbour flood", generator)

    assert turn.citation_ids == ["E1", "E2"]
    assert turn.answer is not None and "[E1]" in turn.answer
    [request] = generator.requests
    assert request.history == ()
    assert [item.evidence_id for item in request.evidence] == ["E1", "E2"]


async def test_follow_up_gets_history_without_citation_markers(
    session_factory: async_sessionmaker[AsyncSession], library: dict[str, uuid.UUID]
) -> None:
    session_id = await new_session(session_factory)
    generator = FakeAnswerGenerator()
    first = await ask(session_factory, session_id, "harbour flood", generator)

    second = await ask(session_factory, session_id, "harbour warning", generator)

    assert second.sequence == 2
    [earlier] = generator.requests[1].history
    assert earlier.question == "harbour flood"
    # The earlier answer is context: its citation markers are gone.
    assert earlier.answer is not None and "[E" not in earlier.answer
    sentences = {sentence.rstrip(".") for sentence in earlier.answer.split(". ")}
    assert sentences == {"Harbour flood is relevant", "Harbour flood warning is relevant"}
    assert first.answer is not None and "[E1]" in first.answer
    # The follow-up still cites only its own evidence.
    assert set(second.citation_ids) <= {item["evidence_id"] for item in second.evidence_snapshot}


async def test_history_is_bounded(
    session_factory: async_sessionmaker[AsyncSession], library: dict[str, uuid.UUID]
) -> None:
    session_id = await new_session(session_factory)
    for number in range(MAX_HISTORY_TURNS + 2):
        await ask(session_factory, session_id, f"harbour {number}")
    generator = FakeAnswerGenerator()

    await ask(session_factory, session_id, "harbour flood", generator)

    history = generator.requests[0].history
    assert [turn.question for turn in history] == [
        f"harbour {number}" for number in range(2, MAX_HISTORY_TURNS + 2)
    ]
    assert all(turn.answer is None for turn in history)


async def test_source_scope(
    session_factory: async_sessionmaker[AsyncSession], library: dict[str, uuid.UUID]
) -> None:
    session_id = await new_session(session_factory, source_id=library["paper"])

    turn = await ask(session_factory, session_id, "harbour flood")

    assert {item["source_id"] for item in turn.evidence_snapshot} == {str(library["paper"])}


async def test_retrieval_mode_comes_from_the_session(
    session_factory: async_sessionmaker[AsyncSession], library: dict[str, uuid.UUID]
) -> None:
    session_id = await new_session(session_factory, retrieval_mode=ResearchMode.SEMANTIC)

    # Semantic search needs local embeddings, which are off here.
    with pytest.raises(ServiceUnavailableError):
        await ask(session_factory, session_id, "harbour flood")


async def test_no_evidence_does_not_ask_the_generator(
    session_factory: async_sessionmaker[AsyncSession], library: dict[str, uuid.UUID]
) -> None:
    session_id = await new_session(session_factory)
    generator = FakeAnswerGenerator()

    turn = await ask(session_factory, session_id, "volcano", generator)

    assert (turn.answer, turn.evidence_snapshot) == (None, [])
    assert generator.requests == []


async def test_turns_saved_at_once_get_different_numbers(
    session_factory: async_sessionmaker[AsyncSession], library: dict[str, uuid.UUID]
) -> None:
    session_id = await new_session(session_factory)

    turns = await asyncio.gather(
        *(ask(session_factory, session_id, f"harbour {number}") for number in range(4))
    )

    assert sorted(turn.sequence for turn in turns) == [1, 2, 3, 4]
    async with session_factory() as session:
        listed = await service(session).list_turns(session_id)
    assert [turn.sequence for turn in listed] == [1, 2, 3, 4]
