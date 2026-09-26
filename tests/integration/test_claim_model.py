import uuid
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.claims.text import normalize_claim_text
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import chunk_text
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

TEXT = "The ministry said unemployment fell to 5% last year."


def claim(text: str = "Unemployment fell to 5%", claim_type: str = "statistic") -> Claim:
    return Claim(text=text, normalized_text=normalize_claim_text(text), claim_type=claim_type)


async def create_chunk_and_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[DocumentChunk, Claim]:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, content=TEXT)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunk_text(TEXT))
        saved_claim = claim()
        session.add(saved_claim)
        await session.commit()
        [chunk] = await repository.list_by_document(document.id)
    return chunk, saved_claim


def evidence(chunk: DocumentChunk, saved: Claim, **values: Any) -> ClaimEvidence:
    fields: dict[str, Any] = {
        "claim_id": saved.id,
        "chunk_id": chunk.id,
        "surface_text": "unemployment fell to 5%",
        "start_char": 18,
        "end_char": 41,
        "confidence": 0.8,
        "provider": "test",
        "model": "claims-1",
    }
    return ClaimEvidence(**(fields | values))


async def add(session_factory: async_sessionmaker[AsyncSession], *rows: Any) -> None:
    async with session_factory() as session:
        session.add_all(rows)
        await session.commit()


async def stored_evidence(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[ClaimEvidence]:
    async with session_factory() as session:
        return list(await session.scalars(select(ClaimEvidence)))


async def test_evidence_is_stored(session_factory: async_sessionmaker[AsyncSession]) -> None:
    chunk, saved = await create_chunk_and_claim(session_factory)

    await add(session_factory, evidence(chunk, saved, evidence_metadata={"sentence": 0}))

    [row] = await stored_evidence(session_factory)
    assert TEXT[row.start_char : row.end_char] == row.surface_text
    assert (row.confidence, row.evidence_metadata) == (0.8, {"sentence": 0})


async def test_one_claim_per_normalized_text_and_type(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add(session_factory, claim())

    async with session_factory() as session:
        session.add(claim("  UNEMPLOYMENT fell   to 5%"))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_other_types_and_texts_are_other_claims(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add(
        session_factory,
        claim(),
        claim(claim_type="quote"),
        claim("Unemployment fell to 6%"),
    )

    async with session_factory() as session:
        assert len(list(await session.scalars(select(Claim)))) == 3


@pytest.mark.parametrize(
    "values",
    [{"text": " "}, {"normalized_text": ""}, {"claim_type": "  "}],
    ids=["blank text", "blank normalized text", "blank type"],
)
async def test_blank_claim_values_are_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, str]
) -> None:
    async with session_factory() as session:
        new = claim()
        for name, value in values.items():
            setattr(new, name, value)
        session.add(new)
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.parametrize(
    "values",
    [
        {"start_char": -1},
        {"end_char": 18},
        {"confidence": 1.01},
        {"confidence": -1},
        {"evidence_metadata": [1]},
        {"claim_id": uuid.uuid4()},
        {"chunk_id": uuid.uuid4()},
    ],
    ids=[
        "negative start",
        "empty span",
        "confidence above one",
        "confidence below zero",
        "metadata list",
        "no claim",
        "no chunk",
    ],
)
async def test_invalid_evidence_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, Any]
) -> None:
    chunk, saved = await create_chunk_and_claim(session_factory)

    async with session_factory() as session:
        session.add(evidence(chunk, saved, **values))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_one_evidence_row_per_place_and_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk, saved = await create_chunk_and_claim(session_factory)
    await add(session_factory, evidence(chunk, saved), evidence(chunk, saved, model="claims-2"))

    async with session_factory() as session:
        session.add(evidence(chunk, saved))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_evidence_goes_with_its_chunk_and_the_claim_stays(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk, saved = await create_chunk_and_claim(session_factory)
    await add(session_factory, evidence(chunk, saved, confidence=None))

    async with session_factory() as session:
        await session.execute(delete(DocumentChunk).where(DocumentChunk.id == chunk.id))
        await session.commit()

    assert await stored_evidence(session_factory) == []
    async with session_factory() as session:
        assert await session.get(Claim, saved.id) is not None


async def test_claim_with_evidence_cannot_be_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk, saved = await create_chunk_and_claim(session_factory)
    await add(session_factory, evidence(chunk, saved))

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(delete(Claim).where(Claim.id == saved.id))
