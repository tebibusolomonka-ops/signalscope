import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ServiceUnavailableError, SignalScopeError
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.reranking.registry import RerankerRegistry
from signalscope.research.citations import validate_citations
from signalscope.research.context import context_text
from signalscope.research.evidence import (
    DEFAULT_EVIDENCE_LIMIT,
    ResearchEvidence,
    ResearchEvidenceService,
    ResearchMode,
)
from signalscope.research.generation import (
    AnswerGeneratorRegistry,
    AnswerRequest,
    GeneratedAnswer,
    generate_answer,
)

logger = logging.getLogger(__name__)


class AnswerGenerationError(ServiceUnavailableError):
    default_message = "Answer generation failed."


@dataclass(frozen=True, slots=True)
class ResearchAnswer:
    # None when no evidence was found. The model is not asked then.
    answer: GeneratedAnswer | None
    # Everything the model was given, in order.
    evidence: tuple[ResearchEvidence, ...]

    @property
    def cited(self) -> list[ResearchEvidence]:
        """The evidence the answer cites, in the order of its citation list."""
        if self.answer is None:
            return []
        by_id = {item.evidence_id: item for item in self.evidence}
        return [by_id[citation_id] for citation_id in self.answer.citation_ids]


class ResearchAnswerService:
    """Answers a question from retrieved evidence, with citations that are checked.

    The answer is only returned when every citation points to evidence the model
    was given, and the text marks exactly the cited evidence.
    """

    def __init__(
        self,
        session: AsyncSession,
        providers: EmbeddingProviderRegistry,
        rerankers: RerankerRegistry,
        generators: AnswerGeneratorRegistry,
    ) -> None:
        self.evidence = ResearchEvidenceService(session, providers, rerankers)
        self.generators = generators

    async def answer(
        self,
        question: str,
        *,
        mode: ResearchMode = ResearchMode.HYBRID,
        limit: int = DEFAULT_EVIDENCE_LIMIT,
        source_id: uuid.UUID | None = None,
    ) -> ResearchAnswer:
        # Checked first, so no search runs when nothing could answer.
        generator = self.generators.only()
        evidence = await self.evidence.build(question, mode=mode, limit=limit, source_id=source_id)
        if not evidence:
            return ResearchAnswer(answer=None, evidence=())
        request = AnswerRequest(
            question=question, evidence=tuple(evidence), context_text=context_text(evidence)
        )
        try:
            answer = await generate_answer(generator, request)
        except SignalScopeError:
            raise
        except Exception as error:
            logger.exception("Answer model %s failed", generator.model_name)
            raise AnswerGenerationError() from error
        return ResearchAnswer(answer=validate_citations(answer, evidence), evidence=tuple(evidence))
