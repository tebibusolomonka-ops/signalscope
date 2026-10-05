import json
import uuid
from datetime import UTC, datetime

from signalscope.core.settings import Environment, Settings
from signalscope.domain.diagnostics.build_metadata import BuildMetadata
from signalscope.domain.diagnostics.deployment_validation import (
    DeploymentRequirementResult,
    DeploymentValidationResult,
    ValidationStatus,
    VerifiedBackupEvidence,
)
from signalscope.domain.diagnostics.release_candidate import (
    EvaluationEvidenceReference,
    ReleaseCandidateService,
)

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def test_manifest_is_deterministic_and_safe() -> None:
    secret = "postgresql+asyncpg://user:secret@database/signalscope"
    settings = Settings(environment=Environment.PRODUCTION, database_url=secret)
    validation = DeploymentValidationResult(
        1,
        (DeploymentRequirementResult("migration", ValidationStatus.MET, "Met."),),
        None,
    )
    first_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    reports = (
        EvaluationEvidenceReference(second_id, "reranking", "data-b", "b" * 64),
        EvaluationEvidenceReference(first_id, "embedding_retrieval", "data-a", "a" * 64),
    )
    backup = VerifiedBackupEvidence(first_id, NOW)

    manifest = ReleaseCandidateService(settings, clock=lambda: NOW).create(
        build=BuildMetadata("0.1.0", "3.12", "abc", "time", "release"),
        migration_head="head",
        validation=validation,
        backup=backup,
        evaluation_reports=reports,
    )
    payload = manifest.to_dict()

    assert payload["created_at"] == NOW.isoformat()
    assert payload["latest_verified_backup"]["backup_id"] == str(first_id)  # type: ignore[index]
    assert [item["report_id"] for item in payload["evaluation_reports"]] == [  # type: ignore[index]
        str(first_id),
        str(second_id),
    ]
    assert payload == manifest.to_dict()
    assert secret not in json.dumps(payload)
