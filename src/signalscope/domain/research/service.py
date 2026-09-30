import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import InvalidInputError, NotFoundError
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.research.turn import ResearchTurn
from signalscope.domain.sources.model import Source
from signalscope.domain.tenancy.scope import ContentScope
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.reranking.registry import RerankerRegistry
from signalscope.research.answering import answer_from_evidence
from signalscope.research.evidence import (
    DEFAULT_EVIDENCE_LIMIT,
    ResearchEvidence,
    ResearchEvidenceService,
    ResearchMode,
)
from signalscope.research.generation import (
    AnswerGeneratorRegistry,
    ConversationTurn,
    GeneratedAnswer,
    strip_citation_markers,
)

# How many earlier turns an answer model sees as conversation context.
MAX_HISTORY_TURNS = 5


SOURCE_IN_OTHER_ORGANIZATION = "The source belongs to another organization."


def evidence_snapshot(evidence: Sequence[ResearchEvidence]) -> list[dict[str, Any]]:
    """The evidence of a turn as it was given to the answer model, as JSON values.

    It keeps the text the model read, but no vectors and no search scores.
    """
    return [
        {
            "evidence_id": item.evidence_id,
            "document_id": str(item.document_id),
            "chunk_id": str(item.chunk_id),
            "source_id": str(item.source_id),
            "title": item.title,
            "url": item.url,
            "excerpt": item.excerpt,
            "text": item.text,
            "chunk_metadata": item.chunk_metadata,
        }
        for item in evidence
    ]


class ResearchSessionService:
    """Multi-turn research: each question in a session is saved with its evidence.

    Every turn searches again for its own question, with the session's mode and
    source. Earlier turns are passed to the answer model as conversation
    context only. They are never evidence: an answer can only cite the evidence
    found for its own turn, and its citations are checked like any answer.

    Without an answer model, turns are still saved, with their evidence and no
    answer, so sessions work before a model is turned on.

    Writes commit before they return. The answer model runs outside any
    transaction.
    """

    def __init__(
        self,
        session: AsyncSession,
        providers: EmbeddingProviderRegistry,
        rerankers: RerankerRegistry,
        generators: AnswerGeneratorRegistry,
    ) -> None:
        self.session = session
        self.providers = providers
        self.rerankers = rerankers
        self.generators = generators

    async def create_session(
        self,
        *,
        title: str | None = None,
        retrieval_mode: ResearchMode = ResearchMode.HYBRID,
        source_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
    ) -> ResearchSession:
        """Start a session. Its source, if any, must belong to the same organization."""
        if source_id is not None:
            source = await self.session.get(Source, source_id)
            if source is None:
                raise NotFoundError("Source was not found.")
            if organization_id is not None and source.organization_id != organization_id:
                raise InvalidInputError(SOURCE_IN_OTHER_ORGANIZATION)
        research = ResearchSession(
            title=title,
            retrieval_mode=retrieval_mode,
            source_id=source_id,
            organization_id=organization_id,
        )
        self.session.add(research)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return research

    async def get_session(self, session_id: uuid.UUID) -> ResearchSession:
        research = await self.session.get(ResearchSession, session_id)
        if research is None:
            raise NotFoundError("Research session was not found.")
        return research

    async def list_sessions(
        self, scope: ContentScope, limit: int, offset: int
    ) -> tuple[list[ResearchSession], int]:
        """Sessions in scope, newest first, with the total that match."""
        condition = scope.owner_condition(ResearchSession.organization_id)
        items = await self.session.scalars(
            select(ResearchSession)
            .where(condition)
            .order_by(ResearchSession.created_at.desc(), ResearchSession.id)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(ResearchSession).where(condition)
        )
        return list(items), total or 0

    async def list_turns(self, session_id: uuid.UUID) -> list[ResearchTurn]:
        """Every turn of a session, oldest first."""
        await self.get_session(session_id)
        turns = await self.session.scalars(
            select(ResearchTurn)
            .where(ResearchTurn.session_id == session_id)
            .order_by(ResearchTurn.sequence)
        )
        return list(turns)

    async def list_turns_page(
        self, session_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[ResearchTurn], int]:
        """One page of a session's turns, oldest first, with the total.

        Turns are ordered by sequence, so a new turn is always added at the
        end. Paging forward from the oldest is stable: an earlier page never
        changes when a turn is added, so loading more never repeats a turn.
        """
        await self.get_session(session_id)
        turns = await self.session.scalars(
            select(ResearchTurn)
            .where(ResearchTurn.session_id == session_id)
            .order_by(ResearchTurn.sequence)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count())
            .select_from(ResearchTurn)
            .where(ResearchTurn.session_id == session_id)
        )
        return list(turns), total or 0

    async def add_turn(
        self,
        session_id: uuid.UUID,
        question: str,
        limit: int = DEFAULT_EVIDENCE_LIMIT,
        scope: ContentScope | None = None,
    ) -> ResearchTurn:
        """Answer question in the session and save it as the next turn.

        The evidence search stays inside scope, which the caller sets to the
        session's organization when authentication is on.
        """
        research = await self.get_session(session_id)
        history = await self._history(session_id)
        evidence = await ResearchEvidenceService(
            self.session, self.providers, self.rerankers
        ).build(
            question,
            mode=research.retrieval_mode,
            limit=limit,
            source_id=research.source_id,
            scope=scope,
        )
        # End the read transaction, so none is open while the model writes.
        await self.session.commit()
        answer = await self._answer(question, evidence, history)
        return await self._save(session_id, question, answer, evidence)

    async def _history(self, session_id: uuid.UUID) -> list[ConversationTurn]:
        recent = await self.session.scalars(
            select(ResearchTurn)
            .where(ResearchTurn.session_id == session_id)
            .order_by(ResearchTurn.sequence.desc())
            .limit(MAX_HISTORY_TURNS)
        )
        return [
            ConversationTurn(
                question=turn.question,
                answer=None if turn.answer is None else strip_citation_markers(turn.answer),
            )
            for turn in reversed(list(recent))
        ]

    async def _answer(
        self,
        question: str,
        evidence: Sequence[ResearchEvidence],
        history: Sequence[ConversationTurn],
    ) -> GeneratedAnswer | None:
        if not evidence or not self.generators.keys():
            return None
        return await answer_from_evidence(self.generators.only(), question, evidence, history)

    async def _save(
        self,
        session_id: uuid.UUID,
        question: str,
        answer: GeneratedAnswer | None,
        evidence: Sequence[ResearchEvidence],
    ) -> ResearchTurn:
        try:
            # The row lock makes turns that are saved at the same time wait for
            # each other, so no two get the same sequence number.
            research = await self.session.get(
                ResearchSession, session_id, with_for_update=True, populate_existing=True
            )
            if research is None:
                raise NotFoundError("Research session was not found.")
            last = await self.session.scalar(
                select(func.max(ResearchTurn.sequence)).where(ResearchTurn.session_id == session_id)
            )
            turn = ResearchTurn(
                session_id=session_id,
                sequence=(last or 0) + 1,
                question=question,
                answer=None if answer is None else answer.text,
                citation_ids=[] if answer is None else list(answer.citation_ids),
                evidence_snapshot=evidence_snapshot(evidence),
            )
            self.session.add(turn)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return turn
