import uuid
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import InvalidInputError
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.reranking.registry import RerankerRegistry
from signalscope.research.evidence import (
    EvidenceCandidate,
    EvidenceChunk,
    ResearchEvidenceService,
    select_evidence,
)

pytestmark = pytest.mark.anyio


def candidate(document_id: uuid.UUID) -> EvidenceCandidate:
    return EvidenceCandidate(
        chunk_id=uuid.uuid4(),
        document_id=document_id,
        source_id=uuid.uuid4(),
        title=None,
        url=None,
        excerpt=None,
        chunk_metadata={},
        scores={},
    )


def chunk(start: int, end: int, text_hash: str | None = None) -> EvidenceChunk:
    return EvidenceChunk(
        text="text", text_hash=text_hash or uuid.uuid4().hex, start_char=start, end_char=end
    )


def test_keeps_search_order_and_limit() -> None:
    items = [candidate(uuid.uuid4()) for _ in range(4)]
    texts = {item.chunk_id: chunk(0, 10) for item in items}

    assert select_evidence(items, texts, 3) == items[:3]


def test_at_most_two_chunks_per_document() -> None:
    document = uuid.uuid4()
    items = [candidate(document) for _ in range(3)] + [candidate(uuid.uuid4())]
    texts = {
        item.chunk_id: chunk(index * 100, index * 100 + 50) for index, item in enumerate(items)
    }

    assert select_evidence(items, texts, 10) == [items[0], items[1], items[3]]


def test_overlapping_chunks_of_one_document_are_skipped() -> None:
    document = uuid.uuid4()
    first, overlapping, apart = candidate(document), candidate(document), candidate(document)
    texts = {
        first.chunk_id: chunk(0, 1200),
        overlapping.chunk_id: chunk(1000, 2200),
        apart.chunk_id: chunk(2200, 3000),
    }

    assert select_evidence([first, overlapping, apart], texts, 10) == [first, apart]


def test_same_text_in_another_document_is_skipped() -> None:
    first, copy = candidate(uuid.uuid4()), candidate(uuid.uuid4())
    texts = {first.chunk_id: chunk(0, 10, "a" * 64), copy.chunk_id: chunk(0, 10, "a" * 64)}

    assert select_evidence([first, copy], texts, 10) == [first]


@pytest.mark.parametrize("limit", [0, 21])
async def test_limit_is_checked_first(limit: int) -> None:
    service = ResearchEvidenceService(
        cast(AsyncSession, None), EmbeddingProviderRegistry(), RerankerRegistry()
    )

    with pytest.raises(InvalidInputError, match="between 1 and 20"):
        await service.build("wind", limit=limit)
