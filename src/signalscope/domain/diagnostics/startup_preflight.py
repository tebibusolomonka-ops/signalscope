from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.build_metadata import (
    BuildMetadata,
    BuildMetadataService,
)
from signalscope.domain.diagnostics.deployment import (
    DeploymentDiagnosticsService,
    DeploymentReport,
)
from signalscope.domain.diagnostics.migration_compatibility import (
    MigrationCompatibilityReport,
    MigrationCompatibilityService,
)
from signalscope.domain.diagnostics.production_config import Level
from signalscope.domain.diagnostics.readiness import ComponentState
from signalscope.storage.blob import BlobStore


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    check: str
    level: Level
    message: str


@dataclass(frozen=True, slots=True)
class StartupPreflightReport:
    checks: tuple[PreflightCheck, ...]
    build: BuildMetadata
    migration: MigrationCompatibilityReport

    @property
    def passed(self) -> bool:
        return not any(check.level is Level.ERROR for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [
                {"check": check.check, "level": check.level.value, "message": check.message}
                for check in self.checks
            ],
            "build": self.build.to_dict(),
            "migration_compatibility": self.migration.to_dict(),
        }


class StartupPreflightService:
    """Run read-only checks needed before starting a deployment."""

    def __init__(
        self,
        settings: Settings,
        *,
        deployment: DeploymentDiagnosticsService | None = None,
        build_metadata: BuildMetadataService | None = None,
        migration: MigrationCompatibilityService | None = None,
    ) -> None:
        self._deployment = deployment or DeploymentDiagnosticsService(settings)
        self._build_metadata = build_metadata or BuildMetadataService(settings)
        self._migration = migration or MigrationCompatibilityService()

    def without_database(self) -> StartupPreflightReport:
        return self._evaluate(
            self._deployment.without_database(), self._migration.database_unavailable()
        )

    async def collect(
        self, session: AsyncSession, blobs: BlobStore | None
    ) -> StartupPreflightReport:
        deployment = await self._deployment.collect(session, blobs)
        migration = await self._migration.check(session)
        return self._evaluate(deployment, migration)

    def _evaluate(
        self, deployment: DeploymentReport, migration: MigrationCompatibilityReport
    ) -> StartupPreflightReport:
        checks = [
            PreflightCheck(finding.check, finding.level, finding.message)
            for finding in deployment.production_config.findings
        ]
        components = (
            {}
            if deployment.readiness is None
            else {c.name: c for c in deployment.readiness.components}
        )
        for name in ("database", "storage"):
            component = components.get(name)
            if component is None:
                checks.append(
                    PreflightCheck(name, Level.ERROR, f"{name.title()} readiness is unavailable.")
                )
            else:
                level = Level.ERROR if component.state is ComponentState.UNAVAILABLE else Level.PASS
                checks.append(PreflightCheck(name, level, component.detail))

        checks.append(
            PreflightCheck(
                "migration",
                Level.PASS if migration.current else Level.ERROR,
                migration.message,
            )
        )

        if not deployment.queues:
            checks.append(
                PreflightCheck("queues", Level.ERROR, "Queue query capability is unavailable.")
            )
        elif all(queue.query_available for queue in deployment.queues):
            checks.append(PreflightCheck("queues", Level.PASS, "All queues can be queried."))
        else:
            checks.append(
                PreflightCheck("queues", Level.ERROR, "One or more queues cannot be queried.")
            )

        build = self._build_metadata.inspect()
        missing = [
            name
            for name, value in (
                ("build SHA", build.build_sha),
                ("build time", build.build_time),
                ("release name", build.release_name),
            )
            if value is None
        ]
        if missing:
            checks.append(
                PreflightCheck(
                    "build_metadata",
                    Level.WARNING,
                    f"Optional metadata is missing: {', '.join(missing)}.",
                )
            )
        else:
            checks.append(
                PreflightCheck("build_metadata", Level.PASS, "Build metadata is configured.")
            )
        return StartupPreflightReport(checks=tuple(checks), build=build, migration=migration)
