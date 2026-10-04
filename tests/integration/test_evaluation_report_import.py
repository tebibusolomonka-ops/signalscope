import hashlib
import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import InvalidInputError
from signalscope.domain.evaluation.import_service import EvaluationReportImportService
from signalscope.domain.evaluation.model import EvaluationReportRecord

pytestmark = pytest.mark.anyio


def report(**overrides):
    base = {
        "report_version": 1,
        "task": "embedding_retrieval",
        "model": "intfloat/multilingual-e5-small",
        "provider": "sentence_transformers",
        "dataset": {"name": "pilot", "fingerprint": "abc123"},
        "created_at": "2026-10-01T00:00:00Z",
        "environment": {
            "python": "3.12",
            "cache_dir": "/home/me/.cache/huggingface",
            "hf_token": "secret",
        },
        "configuration": {},
        "metrics": {"recall@5": 0.8},
        "timings": {"total_seconds": 1.2},
        "warnings": [],
    }
    base.update(overrides)
    return base


async def test_import_stores_once_and_strips_secrets(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first = await EvaluationReportImportService(session).import_report(report())
    async with session_factory() as session:
        again = await EvaluationReportImportService(session).import_report(report())
    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(EvaluationReportRecord))
        stored = (await session.scalars(select(EvaluationReportRecord))).one()

    assert first.created is True
    assert again.created is False
    assert again.record.id == first.record.id
    assert total == 1
    assert stored.environment_summary == {"python": "3.12"}
    assert "hf_token" not in json.dumps(stored.environment_summary)
    assert (
        stored.report_sha256
        == hashlib.sha256(
            (json.dumps(report(), indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
        ).hexdigest()
    )


@pytest.mark.parametrize("task", ["relation_evaluation", "answer_citation"])
async def test_import_each_task(
    session_factory: async_sessionmaker[AsyncSession], task: str
) -> None:
    async with session_factory() as session:
        imported = await EvaluationReportImportService(session).import_report(report(task=task))
    assert imported.record.task == task


async def test_malformed_report_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = EvaluationReportImportService(session)
        with pytest.raises(InvalidInputError):
            await service.import_report(report(task="made_up"))
        with pytest.raises(InvalidInputError):
            await service.import_report(report(metrics="nope"))
        with pytest.raises(InvalidInputError):
            await service.import_report({"report_version": 1})
