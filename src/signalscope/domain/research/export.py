import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import NotFoundError
from signalscope.domain.research.schemas import ResearchSessionRead, ResearchTurnRead
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.research.turn import ResearchTurn


class ResearchSessionExport(BaseModel):
    """A research session as it was: every turn with the evidence it was answered from."""

    session: ResearchSessionRead
    # In order, first turn first.
    turns: list[ResearchTurnRead]


class ResearchSessionExportService:
    """Exports a research session from what was saved with each turn.

    Nothing is searched again: the evidence is the snapshot each turn stored,
    so the export shows what the answer model saw at that time. Prompts,
    vectors and chunk text are left out.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def export(self, session_id: uuid.UUID) -> ResearchSessionExport:
        research = await self.session.get(ResearchSession, session_id)
        if research is None:
            raise NotFoundError("Research session was not found.")
        turns = await self.session.scalars(
            select(ResearchTurn)
            .where(ResearchTurn.session_id == session_id)
            .order_by(ResearchTurn.sequence)
        )
        return ResearchSessionExport(
            session=ResearchSessionRead.model_validate(research),
            turns=[ResearchTurnRead.from_turn(turn) for turn in turns],
        )


def session_markdown(export: ResearchSessionExport) -> str:
    """The export as Markdown. The same export always gives the same text."""
    session = export.session
    lines = [
        f"# {session.title or 'Research session'}",
        "",
        f"Search mode: {session.retrieval_mode.value}",
        f"Source: {session.source_id or 'all sources'}",
        f"Created: {session.created_at.isoformat()}",
    ]
    if not export.turns:
        lines += ["", "No questions yet."]
    for turn in export.turns:
        lines += [
            "",
            f"## Turn {turn.sequence}",
            "",
            f"Question: {turn.question}",
            "",
            f"Answer: {turn.answer or '(no answer)'}",
        ]
        if turn.citation_ids:
            lines += ["", f"Citations: {', '.join(turn.citation_ids)}"]
        lines += ["", "### Evidence", ""]
        if not turn.evidence:
            lines.append("No evidence was found.")
        for item in turn.evidence:
            where = f" ({item.url})" if item.url else ""
            lines.append(
                f"- [{item.evidence_id}] {item.title or '(no title)'}{where}: {item.excerpt}"
            )
    return "\n".join(lines) + "\n"
