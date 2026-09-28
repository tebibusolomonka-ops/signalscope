"""One dataset seen through the dashboard, comparison, timeline, research and investigations.

The numbers must agree across features. No model is used: research turns are
saved without an answer model, and the data is stored directly or through
the file processor.
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import report_event
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.processing.file_import import FileImportService
from signalscope.domain.processing.model import ProcessingJobStatus
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.processing.worker import DocumentProcessingWorker
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio


async def create_source(client: httpx.AsyncClient, name: str) -> uuid.UUID:
    response = await client.post("/sources", json={"type": "upload", "name": name})
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


async def first_chunk(
    session_factory: async_sessionmaker[AsyncSession], source_id: uuid.UUID
) -> DocumentChunk:
    async with session_factory() as session:
        chunk = await session.scalar(
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.source_id == source_id)
            .order_by(DocumentChunk.id)
            .limit(1)
        )
    assert chunk is not None
    return chunk


async def add_entity_and_claim(
    session_factory: async_sessionmaker[AsyncSession], chunk: DocumentChunk
) -> None:
    """The same entity and claim, found in the given chunk."""
    async with session_factory() as session:
        entity = await session.scalar(select(Entity))
        if entity is None:
            entity = Entity(canonical_name="Porto", normalized_name="porto", entity_type="city")
            claim = Claim(text="Water rose", normalized_text="water rose", claim_type="statistic")
            session.add_all([entity, claim])
            await session.flush()
        claim = await session.scalar(select(Claim))
        assert claim is not None
        session.add_all(
            [
                EntityMention(
                    entity_id=entity.id,
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    surface_text=chunk.text[:4],
                    entity_type="city",
                    start_char=0,
                    end_char=4,
                    provider="test",
                    model="m",
                    chunk_text_hash=chunk.text_hash,
                ),
                ClaimEvidence(
                    claim_id=claim.id,
                    chunk_id=chunk.id,
                    surface_text=chunk.text[:4],
                    start_char=0,
                    end_char=4,
                    provider="test",
                    model="m",
                ),
            ]
        )
        await session.commit()


async def get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_features_agree_on_one_dataset(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    wire = await create_source(client, "Wire")
    paper = await create_source(client, "Paper")
    radio = await create_source(client, "Radio")
    today = datetime.now(UTC).replace(hour=0, minute=30, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    # A processed file in the radio source.
    blobs = LocalBlobStore(tmp_path / "blobs")
    async with session_factory() as session:
        await FileImportService(session, blobs).import_file(
            radio, filename="notes.txt", content_type="text/plain", data=b"Harbour notes."
        )
    processor = DocumentProcessor(session_factory, blobs, create_default_parser_registry())
    processed = await DocumentProcessingWorker(session_factory, processor).run_once()
    assert processed.job is not None and processed.job.status is ProcessingJobStatus.COMPLETED
    # One flood that two sources report today, and a closure only the paper reports.
    await report_event(session_factory, wire, "Harbour flood", occurred_at=today)
    await report_event(session_factory, paper, "Harbour flood", occurred_at=today)
    await report_event(
        session_factory, paper, "Bridge closed", event_type="closure", occurred_at=yesterday
    )
    await EventLinkingService(session_factory).link_unclustered()
    await add_entity_and_claim(session_factory, await first_chunk(session_factory, wire))
    await add_entity_and_claim(session_factory, await first_chunk(session_factory, paper))

    # Research and an investigation that keeps it.
    research = (
        await client.post(
            "/research/sessions", json={"title": "Floods", "retrieval_mode": "lexical"}
        )
    ).json()
    turn = await client.post(
        f"/research/sessions/{research['id']}/turns", json={"question": "harbour flood"}
    )
    assert turn.status_code == 201, turn.text
    investigation = (await client.post("/investigations", json={"title": "Harbour"})).json()
    saved = await client.post(
        f"/investigations/{investigation['id']}/research-sessions/{research['id']}"
    )
    assert saved.status_code == 201, saved.text

    overview = await get(client, "/dashboard/overview")
    assert (overview["sources"], overview["documents"], overview["events"]) == (3, 4, 3)
    assert (overview["entities"], overview["claims"], overview["event_clusters"]) == (1, 1, 2)
    assert (overview["research_sessions"], overview["investigations"]) == (1, 1)
    assert overview["pending_processing"] == 0

    sources = await get(client, "/dashboard/sources", days=7)
    assert sum(item["documents_created"] for item in sources["items"]) == overview["documents"]
    assert sources["items"][-1]["documents_created"] == overview["documents"]

    events = await get(client, "/dashboard/events", days=7)
    by_day = {item["date"]: item for item in events["items"]}
    assert (
        by_day[today.date().isoformat()]["events"],
        by_day[today.date().isoformat()]["clusters"],
        by_day[today.date().isoformat()]["cross_source_clusters"],
    ) == (2, 1, 1)
    assert by_day[yesterday.date().isoformat()]["cross_source_clusters"] == 0
    assert sum(item["clusters"] for item in events["items"]) == overview["event_clusters"]

    comparison = await client.post(
        "/sources/compare", json={"source_ids": [str(wire), str(paper), str(radio)]}
    )
    compared = comparison.json()
    assert compared["shared_event_cluster_count"] == sum(
        item["cross_source_clusters"] for item in events["items"]
    )
    assert (compared["shared_entity_count"], compared["shared_claim_count"]) == (1, 1)
    assert (
        sum(item["provenance"]["event_count"] for item in compared["sources"])
        == (overview["events"])
    )
    assert (
        sum(item["provenance"]["document_count"] for item in compared["sources"])
        == (overview["documents"])
    )

    timeline = await get(client, "/timeline")
    assert timeline["total"] == overview["event_clusters"]
    shared = [item for item in timeline["items"] if item["source_count"] >= 2]
    assert [item["title"] for item in shared] == ["Harbour flood"]
    detail = await get(client, f"/event-clusters/{shared[0]['cluster_id']}")
    assert detail["source_count"] == 2

    item = saved.json()
    assert item["snapshot"]["turn_count"] == 1
    session_export = await get(client, f"/research/sessions/{research['id']}/export")
    assert [turn["question"] for turn in session_export["turns"]] == ["harbour flood"]
    investigation_export = await get(client, f"/investigations/{investigation['id']}/export")
    [exported] = investigation_export["items"]
    assert (exported["item_type"], exported["current_reference_exists"]) == (
        "research_session",
        True,
    )
    assert exported["snapshot"] == item["snapshot"]
    markdown = await client.get(
        f"/investigations/{investigation['id']}/export", params={"format": "markdown"}
    )
    assert "## Research sessions\n\n- Floods (lexical, 1 turn)." in markdown.text
