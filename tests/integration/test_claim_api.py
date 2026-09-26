import hashlib
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_claims import FakeClaimExtractor
from signalscope.claims.registry import ClaimExtractorRegistry
from signalscope.domain.claims.model import Claim
from signalscope.domain.claims.queue import ClaimExtractionQueueService
from signalscope.domain.claims.text import normalize_claim_text
from signalscope.domain.claims.worker import ClaimExtractionWorker
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


async def extract(
    session_factory: async_sessionmaker[AsyncSession], *texts: str
) -> list[DocumentChunk]:
    """Store a document with one chunk per text and run the fake extraction on it."""
    chunks = [
        TextChunk(
            position=index,
            text=value,
            start_char=0,
            end_char=len(value),
            text_hash=hashlib.sha256(value.encode()).hexdigest(),
            metadata={"page_number": index + 1},
        )
        for index, value in enumerate(texts)
    ]
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        await session.commit()
        saved = await repository.list_by_document(document.id)
    await ClaimExtractionQueueService(session_factory).queue_chunks(
        [chunk.id for chunk in saved], "test", "number-sentences"
    )
    registry = ClaimExtractorRegistry()
    registry.register(FakeClaimExtractor())
    worker = ClaimExtractionWorker(session_factory, registry)
    while (await worker.run_once()).job is not None:
        pass
    return saved


async def get(client: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_empty(client: httpx.AsyncClient) -> None:
    assert await get(client, "/claims") == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_list_with_evidence_counts(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await extract(
        session_factory, "Unemployment fell to 5%.", "Unemployment fell to 5%. Prices rose 3%."
    )

    page = await get(client, "/claims")

    assert [(item["normalized_text"], item["evidence_count"]) for item in page["items"]] == [
        ("prices rose 3%", 1),
        ("unemployment fell to 5%", 2),
    ]
    assert page["items"][0]["claim_type"] == "statistic"


async def test_text_search_and_type_filter(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await extract(session_factory, "Unemployment fell to 5%. Prices rose 3%.")
    async with session_factory() as session:
        session.add(
            Claim(
                text="Prices rose 3%",
                normalized_text=normalize_claim_text("Prices rose 3%"),
                claim_type="quote",
            )
        )
        await session.commit()

    by_text = await get(client, "/claims", query="  PRICES rose ")
    by_type = await get(client, "/claims", claim_type="Quote")
    nothing = await get(client, "/claims", query="50%")

    assert [item["claim_type"] for item in by_text["items"]] == ["quote", "statistic"]
    assert [item["claim_type"] for item in by_type["items"]] == ["quote"]
    assert nothing["total"] == 0


async def test_pagination(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await extract(session_factory, "One 1. Two 2. Three 3.")

    page = await get(client, "/claims", limit=2, offset=1)

    assert [item["normalized_text"] for item in page["items"]] == ["three 3", "two 2"]
    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 1)


async def test_detail(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    first, second = await extract(
        session_factory, "Unemployment fell to 5%.", "Unemployment fell to 5%."
    )
    [listed] = (await get(client, "/claims"))["items"]

    detail = await get(client, f"/claims/{listed['id']}")

    assert detail["claim"]["id"] == listed["id"]
    assert detail["evidence_count"] == 2
    assert [
        (row["chunk_id"], row["document_id"], row["chunk_metadata"]) for row in detail["evidence"]
    ] == [
        (str(first.id), str(first.document_id), {"page_number": 1}),
        (str(second.id), str(second.document_id), {"page_number": 2}),
    ]
    row = detail["evidence"][0]
    assert (row["surface_text"], row["start_char"], row["end_char"]) == (
        "Unemployment fell to 5%.",
        0,
        24,
    )
    assert (row["confidence"], row["provider"], row["model"]) == (0.8, "test", "number-sentences")


async def test_unknown_claim(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/claims/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Claim was not found."}}
