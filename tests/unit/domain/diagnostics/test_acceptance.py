from signalscope.domain.diagnostics.acceptance import (
    AcceptanceEvidence,
    AcceptanceRunner,
    AcceptanceStatus,
)
from signalscope.domain.diagnostics.acceptance_profile import AcceptanceProfile


def profile() -> AcceptanceProfile:
    return AcceptanceProfile(
        1,
        {
            "deployment": {"migration_current": True, "validation_passes": False},
            "frontend": {"build_passes": True},
        },
    )


def test_all_observed_requirements_pass() -> None:
    evidence = AcceptanceEvidence(
        {
            "deployment.migration_current": True,
            "frontend.build_passes": True,
        },
        {"build_sha": "abc123"},
    )

    result = AcceptanceRunner().run(profile(), evidence)

    assert result.passed is True
    assert result.to_dict()["requirements_met"] == [
        "deployment.migration_current",
        "frontend.build_passes",
    ]
    assert result.to_dict()["evidence_references"] == {"build_sha": "abc123"}


def test_missed_requirement_fails() -> None:
    evidence = AcceptanceEvidence(
        {"deployment.migration_current": False, "frontend.build_passes": True}, {}
    )

    result = AcceptanceRunner().run(profile(), evidence)

    assert result.passed is False
    assert result.checks[0].status is AcceptanceStatus.MISSED


def test_optional_false_requirement_is_not_evaluated() -> None:
    result = AcceptanceRunner().run(
        profile(),
        AcceptanceEvidence(
            {"deployment.migration_current": True, "frontend.build_passes": True}, {}
        ),
    )

    assert "deployment.validation_passes" not in {check.requirement for check in result.checks}


def test_missing_evidence_is_manual_and_warning_is_preserved() -> None:
    result = AcceptanceRunner().run(
        profile(),
        AcceptanceEvidence(
            {"deployment.migration_current": True}, {}, ("Review external TLS settings.",)
        ),
    )

    assert result.passed is True
    assert result.to_dict()["manual_checks"] == ["frontend.build_passes"]
    assert result.to_dict()["warnings"] == ["Review external TLS settings."]
