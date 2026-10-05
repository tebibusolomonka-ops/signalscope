import json
from pathlib import Path

import pytest

from signalscope.domain.diagnostics.acceptance_profile import (
    ACCEPTANCE_PROFILE_VERSION,
    AcceptanceProfileError,
    load_acceptance_profile,
)


def write_profile(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_valid_profile(tmp_path: Path) -> None:
    path = write_profile(
        tmp_path / "profile.json",
        {
            "version": 1,
            "deployment": {"validation_passes": True, "migration_current": True},
            "security": {"auth_enabled": True, "csp_enabled": True},
            "backup": {"verified_backup_exists": True, "max_age_hours": 24},
            "disaster_recovery": {
                "drill_exists": True,
                "verification_max_age_hours": 24,
                "restore_test_required": False,
                "restore_test_max_age_hours": 168,
            },
            "operations": {"startup_preflight_passes": True},
            "frontend": {"lint_passes": True, "tests_pass": True},
            "model_evaluation": {"quality_gate_evidence_exists": False},
        },
    )

    profile = load_acceptance_profile(path)

    assert profile.version == ACCEPTANCE_PROFILE_VERSION
    assert profile.section("backup") == {
        "verified_backup_exists": True,
        "max_age_hours": 24,
    }
    assert profile.to_dict()["security"] == {"auth_enabled": True, "csp_enabled": True}


def test_optional_sections_can_be_omitted(tmp_path: Path) -> None:
    profile = load_acceptance_profile(write_profile(tmp_path / "profile.json", {"version": 1}))

    assert profile.sections == {}
    assert profile.section("model_evaluation") is None


@pytest.mark.parametrize(
    "value",
    [
        {"version": 2},
        {"version": 1, "unknown": {}},
        {"version": 1, "backup": {"max_age_hours": 0}},
        {"version": 1, "security": {"auth_enabled": "yes"}},
        {"version": 1, "frontend": {"unknown": True}},
    ],
)
def test_invalid_profiles_are_rejected(tmp_path: Path, value: object) -> None:
    path = write_profile(tmp_path / "profile.json", value)

    with pytest.raises(AcceptanceProfileError):
        load_acceptance_profile(path)
