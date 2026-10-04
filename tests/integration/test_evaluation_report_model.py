import hashlib

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.evaluation.model import EvaluationReportRecord

pytestmark = pytest.mark.anyio


def record(**overrides: object) -> EvaluationReportRecord:
    data = {
        "task": "embedding_retrieval",
        "model": "intfloat/multilingual-e5-small",
        "provider": "sentence_transformers",
        "dataset_name": "pilot",
        "dataset_fingerprint": "abc123",
        "report_version": 1,
        "report_json": {"metrics": {"recall@5": 0.8}},
        "report_sha256": "a" * 64,
        "environment_summary": {"python": "3.12"},
    }
    data.update(overrides)
    return EvaluationReportRecord(**data)


async def test_store_and_read(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        session.add(record())
        await session.commit()
    async with session_factory() as session:
        stored = (await session.scalars(select(EvaluationReportRecord))).one()
    assert stored.task == "embedding_retrieval"
    assert stored.report_json == {"metrics": {"recall@5": 0.8}}
    assert stored.created_at is not None


async def test_unknown_task_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(record(task="made_up", report_sha256="b" * 64))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_hash_must_be_hex(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        session.add(record(report_sha256="not-hex"))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_hash_is_unique(session_factory: async_sessionmaker[AsyncSession]) -> None:
    sha = hashlib.sha256(b"x").hexdigest()
    async with session_factory() as session:
        session.add(record(report_sha256=sha))
        await session.commit()
    async with session_factory() as session:
        session.add(record(report_sha256=sha, dataset_fingerprint="other"))
        with pytest.raises(IntegrityError):
            await session.commit()
