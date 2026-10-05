from collections.abc import Mapping
from typing import Any

from signalscope.api.middleware import SECURITY_HEADERS
from signalscope.api.security_policy import content_security_policy
from signalscope.core.settings import Environment, Settings
from signalscope.domain.diagnostics.acceptance import AcceptanceEvidence
from signalscope.domain.diagnostics.deployment_validation import DeploymentValidationResult
from signalscope.domain.diagnostics.production_config import ProductionConfigurationValidator
from signalscope.domain.diagnostics.startup_preflight import StartupPreflightReport


class SecurityDeploymentAcceptanceService:
    """Describe configured security and deployment controls without secrets."""

    def __init__(
        self,
        settings: Settings,
        *,
        security_headers: Mapping[str, str] = SECURITY_HEADERS,
        csp: str | None = None,
    ) -> None:
        self._settings = settings
        self._security_headers = security_headers
        self._csp = content_security_policy(settings) if csp is None else csp

    def collect(
        self,
        preflight: StartupPreflightReport,
        *,
        deployment_validation: DeploymentValidationResult | None = None,
        support_bundle_available: bool | None = None,
    ) -> AcceptanceEvidence:
        production = ProductionConfigurationValidator(self._settings).validate()
        throttle = (
            self._settings.auth_login_window_seconds > 0
            and self._settings.auth_login_max_failures > 0
            and self._settings.auth_login_block_seconds > 0
        )
        absolute_expiry = self._settings.auth_session_max_age_seconds > 0
        idle_expiry = self._settings.auth_session_idle_seconds > 0
        values: dict[str, bool | None] = {
            "security.auth_enabled": self._settings.auth_enabled,
            "security.login_throttling_configured": throttle,
            "security.session_expiry_configured": absolute_expiry and idle_expiry,
            "security.absolute_session_expiry_configured": absolute_expiry,
            "security.idle_session_expiry_configured": idle_expiry,
            "security.security_headers_enabled": bool(self._security_headers),
            "security.csp_enabled": bool(self._csp),
            "security.support_bundle_redaction_succeeds": support_bundle_available,
            "deployment.production_configuration_valid": not production.has_errors,
            "deployment.migration_current": preflight.migration.current,
            "deployment.validation_passes": (
                None if deployment_validation is None else deployment_validation.passed
            ),
            "operations.support_bundle_works": support_bundle_available,
        }
        facts: dict[str, Any] = {
            "security": {
                "authentication_enabled": self._settings.auth_enabled,
                "login_throttling": {
                    "configured": throttle,
                    "window_seconds": self._settings.auth_login_window_seconds,
                    "max_failures": self._settings.auth_login_max_failures,
                    "block_seconds": self._settings.auth_login_block_seconds,
                },
                "session_expiry": {
                    "absolute_seconds": self._settings.auth_session_max_age_seconds,
                    "idle_seconds": self._settings.auth_session_idle_seconds,
                },
                "security_headers": {
                    "enabled": bool(self._security_headers),
                    "names": sorted(self._security_headers),
                },
                "content_security_policy": {
                    "enabled": bool(self._csp),
                    "production_mode": self._settings.environment is Environment.PRODUCTION,
                },
                "support_bundle_capability": support_bundle_available,
            },
            "deployment": {
                "production_configuration": {
                    "valid": not production.has_errors,
                    "checks": [
                        {"check": finding.check, "level": finding.level.value}
                        for finding in production.findings
                    ],
                },
                "migration_compatibility": preflight.migration.to_dict(),
                "validation": (
                    None if deployment_validation is None else deployment_validation.to_dict()
                ),
            },
        }
        references = {
            "migration_revision": ",".join(preflight.migration.database_revisions),
            "application_migration_head": ",".join(preflight.migration.application_heads),
        }
        return AcceptanceEvidence(values, references, facts=facts)
