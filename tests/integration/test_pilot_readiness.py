import dataclasses
import hashlib
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.pilot_readiness import CheckStatus, PilotReadinessEvaluator
from signalscope.domain.evaluation.model import EvaluationReportRecord
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio


def statuses(report: object) -> dict[str, CheckStatus]:
    return {check.name: check.status for check in report.checks}  # type: ignore[attr-defined]


async def test_database_checks_pass_and_model_evidence_is_separate(
    migrated_database: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = dataclasses.replace(migrated_database, blob_dir=tmp_path / "blobs")
    blobs = LocalBlobStore(settings.blob_dir)
    evaluator = PilotReadinessEvaluator(settings)

    async with session_factory() as session:
        before = await evaluator.evaluate(session, blobs)

    result = statuses(before)
    assert result["readiness_database"] is CheckStatus.PASSED
    assert result["readiness_storage"] is CheckStatus.PASSED
    assert result["readiness_queue"] is CheckStatus.PASSED
    assert result["migration"] is CheckStatus.PASSED
    # Model evidence is reported in its own section and never as a failed check.
    assert before.model_section["evaluation_evidence_available"] is False
    assert not any(check.name.startswith("model") for check in before.checks)

    async with session_factory() as session:
        session.add(
            EvaluationReportRecord(
                task="embedding_retrieval",
                model="e5-small",
                provider="local",
                dataset_name="pilot",
                dataset_fingerprint="abc123",
                report_version=1,
                report_json={},
                report_sha256=hashlib.sha256(b"report").hexdigest(),
                environment_summary={},
            )
        )
        await session.commit()

    async with session_factory() as session:
        after = await evaluator.evaluate(session, blobs)

    assert after.model_section["evaluation_evidence_available"] is True
    assert after.model_section["evaluation_reports"] == 1
