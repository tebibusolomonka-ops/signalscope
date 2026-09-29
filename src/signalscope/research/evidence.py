"""Evidence for a research question: the chunks that best answer a query.

Search results are turned into a short, deduplicated list of chunks, each with
a response-local ID such as E1. A later step can hand this list to a language
model as citable context. Nothing here generates text.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import InvalidInputError
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.search.hybrid_service import HybridSearchService
from signalscope.domain.search.repository import PUBLIC_SEARCH_LIMIT
from signalscope.domain.search.reranked_service import RerankedSearchService
from signalscope.domain.search.semantic_service import SemanticSearchService
from signalscope.domain.search.service import SearchService
from signalscope.embeddings.models import MULTILINGUAL_E5_SMALL
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.reranking.models import MMARCO_MINILM
from signalscope.reranking.registry import RerankerRegistry

DEFAULT_EVIDENCE_LIMIT = 8
MAX_EVIDENCE_LIMIT = 20
# At most this many chunks come from one document, so one long document
# cannot fill the whole list.
MAX_PER_DOCUMENT = 2
# Search returns this many candidates per evidence item, so dropped
# duplicates can be replaced.
CANDIDATE_MULTIPLIER = 3
# Excerpts cut from the chunk text, when the search gave none, are this long.
EXCERPT_LENGTH = 300


class ResearchMode(StrEnum):
    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"
    RERANKED = "reranked"


@dataclass(frozen=True, slots=True)
class ResearchEvidence:
    # A response-local ID, E1, E2 and so on, in order. Not a lasting citation.
    evidence_id: str
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    url: str | None
    excerpt: str
    # The full chunk text, for building context. APIs may leave it out.
    text: str
    chunk_metadata: dict[str, Any]
    # The scores of the search mode, such as {"hybrid_score": 0.03}.
    scores: dict[str, float | int | None]


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    url: str | None
    excerpt: str | None
    chunk_metadata: dict[str, Any]
    scores: dict[str, float | int | None]


@dataclass(frozen=True, slots=True)
class EvidenceChunk:
    text: str
    text_hash: str
    start_char: int
    end_char: int


class ResearchEvidenceService:
    """Finds and selects evidence chunks for a query. It never writes to the database."""

    def __init__(
        self,
        session: AsyncSession,
        providers: EmbeddingProviderRegistry,
        rerankers: RerankerRegistry,
    ) -> None:
        self.session = session
        self.providers = providers
        self.rerankers = rerankers

    async def build(
        self,
        query: str,
        *,
        mode: ResearchMode = ResearchMode.HYBRID,
        limit: int = DEFAULT_EVIDENCE_LIMIT,
        source_id: uuid.UUID | None = None,
    ) -> list[ResearchEvidence]:
        if not 1 <= limit <= MAX_EVIDENCE_LIMIT:
            raise InvalidInputError(f"Limit must be between 1 and {MAX_EVIDENCE_LIMIT}.")
        candidates = await self._candidates(
            query, mode, min(limit * CANDIDATE_MULTIPLIER, PUBLIC_SEARCH_LIMIT), source_id
        )
        texts = await self._chunk_texts([candidate.chunk_id for candidate in candidates])
        chosen = select_evidence(candidates, texts, limit)
        return [
            ResearchEvidence(
                evidence_id=f"E{number}",
                document_id=candidate.document_id,
                chunk_id=candidate.chunk_id,
                source_id=candidate.source_id,
                title=candidate.title,
                url=candidate.url,
                excerpt=candidate.excerpt or _cut(texts[candidate.chunk_id].text),
                text=texts[candidate.chunk_id].text,
                chunk_metadata=candidate.chunk_metadata,
                scores=candidate.scores,
            )
            for number, candidate in enumerate(chosen, start=1)
        ]

    async def _candidates(
        self, query: str, mode: ResearchMode, limit: int, source_id: uuid.UUID | None
    ) -> list[EvidenceCandidate]:
        provider, model = MULTILINGUAL_E5_SMALL.provider, MULTILINGUAL_E5_SMALL.model
        if mode is ResearchMode.LEXICAL:
            lexical = await SearchService(self.session).search(
                query, limit=limit, source_id=source_id
            )
            return [
                EvidenceCandidate(
                    item.chunk_id,
                    item.document_id,
                    item.source_id,
                    item.title,
                    item.url,
                    item.excerpt,
                    item.chunk_metadata,
                    {"rank": item.rank},
                )
                for item in lexical
            ]
        if mode is ResearchMode.SEMANTIC:
            semantic = await SemanticSearchService(self.session, self.providers).search(
                query, limit=limit, source_id=source_id, provider=provider, model=model
            )
            return [
                EvidenceCandidate(
                    item.chunk_id,
                    item.document_id,
                    item.source_id,
                    item.title,
                    item.url,
                    None,
                    item.chunk_metadata,
                    {"similarity": item.similarity},
                )
                for item in semantic
            ]
        if mode is ResearchMode.HYBRID:
            hybrid = await HybridSearchService(self.session, self.providers).search(
                query, limit=limit, source_id=source_id, provider=provider, model=model
            )
            return [
                EvidenceCandidate(
                    item.chunk_id,
                    item.document_id,
                    item.source_id,
                    item.title,
                    item.url,
                    item.excerpt,
                    item.chunk_metadata,
                    {
                        "hybrid_score": item.hybrid_score,
                        "lexical_rank": item.lexical_rank,
                        "vector_similarity": item.vector_similarity,
                    },
                )
                for item in hybrid
            ]
        reranked = await RerankedSearchService(self.session, self.providers, self.rerankers).search(
            query,
            limit=limit,
            source_id=source_id,
            reranker_provider=MMARCO_MINILM.provider,
            reranker_model=MMARCO_MINILM.model,
            provider=provider,
            model=model,
        )
        return [
            EvidenceCandidate(
                item.chunk_id,
                item.document_id,
                item.source_id,
                item.title,
                item.url,
                item.excerpt,
                item.chunk_metadata,
                {"hybrid_score": item.hybrid_score, "reranker_score": item.reranker_score},
            )
            for item in reranked
        ]

    async def _chunk_texts(self, chunk_ids: list[uuid.UUID]) -> dict[uuid.UUID, EvidenceChunk]:
        if not chunk_ids:
            return {}
        rows = await self.session.execute(
            select(
                DocumentChunk.id,
                DocumentChunk.text,
                DocumentChunk.text_hash,
                DocumentChunk.start_char,
                DocumentChunk.end_char,
            ).where(DocumentChunk.id.in_(chunk_ids))
        )
        return {
            chunk_id: EvidenceChunk(text, text_hash, start, end)
            for chunk_id, text, text_hash, start, end in rows
        }


def select_evidence(
    candidates: Sequence[EvidenceCandidate], texts: dict[uuid.UUID, EvidenceChunk], limit: int
) -> list[EvidenceCandidate]:
    """Pick up to limit candidates in their search order, dropping repeats.

    A candidate is skipped when its document already has MAX_PER_DOCUMENT
    chunks, when it overlaps a chosen chunk of the same document, or when a
    chosen chunk has exactly the same text.
    """
    chosen: list[EvidenceCandidate] = []
    seen_texts: set[str] = set()
    for candidate in candidates:
        chunk = texts.get(candidate.chunk_id)
        if chunk is None or chunk.text_hash in seen_texts:
            continue
        same_document = [
            texts[other.chunk_id] for other in chosen if other.document_id == candidate.document_id
        ]
        if len(same_document) >= MAX_PER_DOCUMENT:
            continue
        # Neighbouring chunks share some text, so they would repeat each other.
        if any(
            chunk.start_char < other.end_char and other.start_char < chunk.end_char
            for other in same_document
        ):
            continue
        chosen.append(candidate)
        seen_texts.add(chunk.text_hash)
        if len(chosen) == limit:
            break
    return chosen


def _cut(text: str) -> str:
    """The start of text, ending at a word boundary when one is near."""
    if len(text) <= EXCERPT_LENGTH:
        return text
    cut = text[:EXCERPT_LENGTH]
    space = cut.rfind(" ")
    return (cut[:space] if space > EXCERPT_LENGTH // 2 else cut).rstrip() + " ..."
