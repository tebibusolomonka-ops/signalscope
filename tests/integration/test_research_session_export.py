import uuid

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from fake_answers import FakeAnswerGenerator
from signalscope.core.errors import NotFoundError
from signalscope.domain.documents.model import Document
from signalscope.domain.research.export import ResearchSessionExportService, session_markdown
from signalscope.domain.research.service import ResearchSessionService
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.reranking.registry import RerankerRegistry
from signalscope.research.evidence import ResearchMode
from signalscope.research.generation import AnswerGeneratorRegistry

pytestmark = pytest.mark.anyio


def sessions(session: AsyncSession) -> ResearchSessionService:
    generators = AnswerGeneratorRegistry()
    generators.register(FakeAnswerGenerator())
    return ResearchSessionService(
        session, EmbeddingProviderRegistry(), RerankerRegistry(), generators
    )


async def test_export_uses_what_each_turn_saw(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, "Wire")
    await report_event(session_factory, source, "Harbour flood")
    await report_event(session_factory, source, "Bridge closed")
    async with session_factory() as session:
        research = await sessions(session).create_session(
            title="Floods", retrieval_mode=ResearchMode.LEXICAL
        )
        await sessions(session).add_turn(research.id, "harbour flood")
        await sessions(session).add_turn(research.id, "bridge closed")
    # A later change to a document does not change what the turns saw.
    async with session_factory() as session:
        await session.execute(update(Document).values(title="Renamed"))
        await session.commit()

    async with session_factory() as session:
        export = await ResearchSessionExportService(session).export(research.id)

    assert (export.session.title, export.session.retrieval_mode) == ("Floods", ResearchMode.LEXICAL)
    assert [turn.sequence for turn in export.turns] == [1, 2]
    first, second = export.turns
    assert (first.question, first.citation_ids) == ("harbour flood", ["E1"])
    assert [item.title for item in first.evidence] == ["Harbour flood"]
    assert [item.title for item in second.citations] == ["Bridge closed"]
    text = session_markdown(export)
    assert "## Turn 2" in text
    assert "- [E1] Harbour flood: " in text
    assert "Renamed" not in text


async def test_empty_session(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        research = await sessions(session).create_session(title="Nothing yet")
        export = await ResearchSessionExportService(session).export(research.id)

    assert export.turns == []
    assert session_markdown(export).endswith("No questions yet.\n")


async def test_unknown_session(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Research session"):
            await ResearchSessionExportService(session).export(uuid.uuid4())
