from pathlib import Path

import pytest

from signalscope.core.settings import Environment, Settings
from signalscope.domain.diagnostics.acceptance import AcceptanceRunner, AcceptanceStatus
from signalscope.domain.diagnostics.acceptance_profile import AcceptanceProfile
from signalscope.domain.diagnostics.build_metadata import BuildMetadata
from signalscope.domain.diagnostics.deployment_validation import (
    DeploymentRequirementResult,
    DeploymentValidationResult,
    ValidationStatus,
)
from signalscope.domain.diagnostics.migration_compatibility import (
    MigrationCompatibilityReport,
    MigrationCompatibilityState,
)
from signalscope.domain.diagnostics.security_acceptance import (
    SecurityDeploymentAcceptanceService,
)
from signalscope.domain.diagnostics.startup_preflight import StartupPreflightReport

PASSWORD = "private-database-password"


def settings(**changes: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.PRODUCTION,
        "auth_enabled": True,
        "database_url": f"postgresql+asyncpg://user:{PASSWORD}@db/signalscope",
        "blob_dir": Path("/srv/blobs"),
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


def preflight(
    state: MigrationCompatibilityState = MigrationCompatibilityState.CURRENT,
) -> StartupPreflightReport:
    return StartupPreflightReport(
        (),
        BuildMetadata("1.0", "3.12", "abc", "2026-10-05T12:00:00Z", "final"),
        MigrationCompatibilityReport(state, ("head",), ("head",), "Migration state."),
    )


def deployment(passed: bool = True) -> DeploymentValidationResult:
    status = ValidationStatus.MET if passed else ValidationStatus.MISSED
    return DeploymentValidationResult(
        1,
        (DeploymentRequirementResult("authentication", status, "Factual result."),),
        None,
    )


def profile(**requirements: bool) -> AcceptanceProfile:
    sections: dict[str, dict[str, bool | int]] = {}
    for key, required in requirements.items():
        section, name = key.split("__", 1)
        sections.setdefault(section, {})[name] = required
    return AcceptanceProfile(1, sections)


def status_for(
    requirement: str,
    *,
    configured: Settings | None = None,
    migration: MigrationCompatibilityState = MigrationCompatibilityState.CURRENT,
    validation: DeploymentValidationResult | None = None,
    support: bool | None = True,
    headers: dict[str, str] | None = None,
    csp: str | None = None,
) -> AcceptanceStatus:
    section, name = requirement.split(".", 1)
    acceptance_profile = profile(**{f"{section}__{name}": True})
    service = SecurityDeploymentAcceptanceService(
        configured or settings(),
        security_headers={"X-Test": "on"} if headers is None else headers,
        csp="default-src 'self'" if csp is None else csp,
    )
    evidence = service.collect(
        preflight(migration),
        deployment_validation=validation,
        support_bundle_available=support,
    )
    return AcceptanceRunner().run(acceptance_profile, evidence).checks[0].status


@pytest.mark.parametrize(
    "requirement",
    [
        "security.auth_enabled",
        "security.login_throttling_configured",
        "security.absolute_session_expiry_configured",
        "security.idle_session_expiry_configured",
        "security.security_headers_enabled",
        "security.csp_enabled",
        "security.support_bundle_redaction_succeeds",
        "deployment.production_configuration_valid",
        "deployment.migration_current",
        "deployment.validation_passes",
        "operations.support_bundle_works",
    ],
)
def test_all_required_evidence_can_be_met(requirement: str) -> None:
    assert status_for(requirement, validation=deployment()) is AcceptanceStatus.MET


def test_disabled_authentication_is_missed() -> None:
    assert (
        status_for("security.auth_enabled", configured=settings(auth_enabled=False))
        is AcceptanceStatus.MISSED
    )


def test_missing_login_throttle_is_missed() -> None:
    configured = settings()
    object.__setattr__(configured, "auth_login_max_failures", 0)

    assert (
        status_for("security.login_throttling_configured", configured=configured)
        is AcceptanceStatus.MISSED
    )


@pytest.mark.parametrize(
    ("field", "requirement"),
    [
        ("auth_session_max_age_seconds", "security.absolute_session_expiry_configured"),
        ("auth_session_idle_seconds", "security.idle_session_expiry_configured"),
    ],
)
def test_missing_session_expiry_is_missed(field: str, requirement: str) -> None:
    configured = settings()
    object.__setattr__(configured, field, 0)

    assert status_for(requirement, configured=configured) is AcceptanceStatus.MISSED


def test_missing_headers_and_csp_are_missed() -> None:
    assert status_for("security.security_headers_enabled", headers={}) is AcceptanceStatus.MISSED
    assert status_for("security.csp_enabled", csp="") is AcceptanceStatus.MISSED


def test_migration_and_deployment_failures_are_missed() -> None:
    assert (
        status_for("deployment.migration_current", migration=MigrationCompatibilityState.BEHIND)
        is AcceptanceStatus.MISSED
    )
    assert (
        status_for("deployment.validation_passes", validation=deployment(False))
        is AcceptanceStatus.MISSED
    )


def test_missing_support_capability_is_missed_and_unobserved_validation_is_manual() -> None:
    assert status_for("operations.support_bundle_works", support=False) is AcceptanceStatus.MISSED
    assert status_for("deployment.validation_passes", validation=None) is AcceptanceStatus.MANUAL


def test_optional_requirements_are_not_checked() -> None:
    acceptance_profile = profile(security__auth_enabled=False)
    evidence = SecurityDeploymentAcceptanceService(settings(auth_enabled=False)).collect(
        preflight(), support_bundle_available=True
    )

    assert AcceptanceRunner().run(acceptance_profile, evidence).checks == ()


def test_output_has_no_secrets_or_tenant_content() -> None:
    acceptance_profile = profile(
        security__auth_enabled=True,
        deployment__production_configuration_valid=True,
    )
    evidence = SecurityDeploymentAcceptanceService(settings()).collect(
        preflight(), deployment_validation=deployment(), support_bundle_available=True
    )
    rendered = AcceptanceRunner().run(acceptance_profile, evidence).to_dict()
    text = str(rendered)

    assert PASSWORD not in text
    assert "database_url" not in text
    assert "token" not in text
    assert "tenant content" not in text
    assert rendered["evidence"]["security"]["content_security_policy"] == {
        "enabled": True,
        "production_mode": True,
    }
