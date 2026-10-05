import json
from pathlib import Path

import pytest

from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.acceptance_profile import AcceptanceProfile
from signalscope.domain.diagnostics.release_readiness import ReleaseReadinessService

pytestmark = pytest.mark.anyio


async def test_without_database_reports_missing_facts_without_secrets() -> None:
    password = "do-not-print-this"
    settings = Settings(database_url=None)
    profile = AcceptanceProfile(
        1,
        {
            "deployment": {"migration_current": True, "validation_passes": True},
            "backup": {"verified_backup_exists": True},
            "model_evaluation": {"quality_gate_evidence_exists": True},
        },
    )

    report = await ReleaseReadinessService(settings).collect(profile, session=None, blobs=None)
    payload = report.to_dict()
    rendered = json.dumps(payload)

    assert payload["migration_compatibility"]["current"] is False
    assert payload["deployment_validation"] is None
    assert payload["latest_verified_backup_evidence"] is None
    assert payload["model_evaluation_evidence"] == {"available": False, "reports": []}
    assert set(payload["acceptance"]["requirements_missed"]) == {
        "deployment.migration_current",
        "model_evaluation.quality_gate_evidence_exists",
    }
    assert payload["acceptance"]["manual_checks"] == [
        "backup.verified_backup_exists",
        "deployment.validation_passes",
    ]
    assert password not in rendered
    assert "database_url" not in rendered


async def test_service_does_not_write_an_output_file(tmp_path: Path) -> None:
    profile = AcceptanceProfile(1, {})

    await ReleaseReadinessService(Settings()).collect(profile, session=None, blobs=None)

    assert list(tmp_path.iterdir()) == []
