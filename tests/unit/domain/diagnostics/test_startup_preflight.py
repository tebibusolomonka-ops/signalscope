from pathlib import Path

import pytest

from signalscope.core.settings import Environment, Settings
from signalscope.domain.diagnostics.build_metadata import BuildMetadataService
from signalscope.domain.diagnostics.deployment import (
    DeploymentDiagnosticsService,
    DeploymentReport,
)
from signalscope.domain.diagnostics.migration_compatibility import (
    MigrationCompatibilityReport,
    MigrationCompatibilityService,
    MigrationCompatibilityState,
)
from signalscope.domain.diagnostics.production_config import (
    Level,
    ProductionConfigurationValidator,
)
from signalscope.domain.diagnostics.queue_readiness import QueueObservation
from signalscope.domain.diagnostics.readiness import (
    ComponentReadiness,
    ComponentState,
    ReadinessReport,
)
from signalscope.domain.diagnostics.startup_preflight import StartupPreflightService
from signalscope.storage.blob import BlobStorageError

pytestmark = pytest.mark.anyio


def production_settings(**changes: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.PRODUCTION,
        "auth_enabled": True,
        "database_url": "postgresql+asyncpg://user:secret@database/signalscope",
        "blob_dir": Path("/var/lib/signalscope/blobs"),
        "build_sha": "abc123",
        "build_time": "2026-10-05T10:00:00Z",
        "release_name": "October release",
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


def deployment_report(
    settings: Settings,
    *,
    database: ComponentState = ComponentState.READY,
    storage: ComponentState = ComponentState.READY,
    current: str | None = "head",
    head: str | None = "head",
    queues_queryable: bool = True,
) -> DeploymentReport:
    readiness = ReadinessReport(
        components=(
            ComponentReadiness("database", database, True, "Database check."),
            ComponentReadiness("storage", storage, True, "Storage check."),
        )
    )
    queue = QueueObservation("ingestion", queues_queryable, 0, 0, None, 0)
    return DeploymentReport(
        environment={},
        production_config=ProductionConfigurationValidator(settings).validate(),
        readiness=readiness,
        queues=(queue,),
        migration_current=current,
        migration_head=head,
    )


def service(settings: Settings, report: DeploymentReport) -> StartupPreflightService:
    state = (
        MigrationCompatibilityState.CURRENT
        if report.migration_current == report.migration_head
        else MigrationCompatibilityState.BEHIND
    )
    migration_report = MigrationCompatibilityReport(
        state,
        () if report.migration_current is None else (report.migration_current,),
        () if report.migration_head is None else (report.migration_head,),
        "Migration check.",
    )
    return StartupPreflightService(
        settings,
        deployment=FakeDeployment(report),  # type: ignore[arg-type]
        build_metadata=BuildMetadataService(
            settings,
            version_lookup=lambda _: "0.1.0",
            python_version=lambda: "3.12.10",
        ),
        migration=FakeMigration(migration_report),  # type: ignore[arg-type]
    )


class FakeDeployment:
    def __init__(self, report: DeploymentReport) -> None:
        self.report = report

    def without_database(self) -> DeploymentReport:
        return self.report


class FakeMigration:
    def __init__(self, report: MigrationCompatibilityReport) -> None:
        self.report = report

    def database_unavailable(self) -> MigrationCompatibilityReport:
        return self.report


class FakeGraph:
    def heads(self) -> tuple[str, ...]:
        return ("head",)

    def knows(self, revision: str) -> bool:
        return revision in {"head", "old"}

    def is_ancestor(self, older: str, newer: str) -> bool:
        return older == "old" and newer == "head"


def levels(report: object) -> dict[str, Level]:
    return {check.check: check.level for check in report.checks}  # type: ignore[attr-defined]


async def test_good_state_passes() -> None:
    settings = production_settings()
    report = service(settings, deployment_report(settings)).without_database()

    assert report.passed is True
    assert Level.ERROR not in levels(report).values()


async def test_database_unavailable_blocks_startup() -> None:
    settings = production_settings()
    report = service(
        settings,
        deployment_report(settings, database=ComponentState.UNAVAILABLE),
    ).without_database()

    assert report.passed is False
    assert levels(report)["database"] is Level.ERROR


async def test_migration_mismatch_blocks_startup() -> None:
    settings = production_settings()
    report = service(
        settings, deployment_report(settings, current="old", head="head")
    ).without_database()

    assert levels(report)["migration"] is Level.ERROR


async def test_storage_failure_blocks_startup() -> None:
    settings = production_settings()
    report = service(
        settings,
        deployment_report(settings, storage=ComponentState.UNAVAILABLE),
    ).without_database()

    assert levels(report)["storage"] is Level.ERROR


async def test_auth_configuration_failure_blocks_startup() -> None:
    settings = production_settings(auth_enabled=False)
    report = service(settings, deployment_report(settings)).without_database()

    assert levels(report)["authentication"] is Level.ERROR


class ReadOnlySession:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.scalar_calls = 0

    async def execute(self, _statement: object) -> object:
        self.execute_calls += 1
        return object()

    async def scalar(self, statement: object) -> int | str | None:
        self.scalar_calls += 1
        query = str(statement)
        if "alembic_version" in query:
            return "head"
        if "min(" in query.lower():
            return None
        return 0

    async def scalars(self, _statement: object) -> object:
        class Revisions:
            def all(self) -> list[str]:
                return ["head"]

        return Revisions()


class ReadOnlyBlobs:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def exists(self, key: str) -> bool:
        self.keys.append(key)
        return False

    async def put(self, key: str, data: bytes) -> None:
        raise AssertionError("preflight must not write storage")

    async def get(self, key: str) -> bytes:
        raise AssertionError("preflight must not read tenant blobs")

    async def delete(self, key: str) -> None:
        raise AssertionError("preflight must not delete storage")


async def test_preflight_only_queries_dependencies() -> None:
    settings = production_settings()
    session = ReadOnlySession()
    blobs = ReadOnlyBlobs()
    deployment = DeploymentDiagnosticsService(settings, migration_head=lambda: "head")
    preflight = StartupPreflightService(
        settings,
        deployment=deployment,
        migration=MigrationCompatibilityService(FakeGraph()),
    )

    report = await preflight.collect(session, blobs)  # type: ignore[arg-type]

    assert report.passed is True
    assert session.execute_calls == 1
    assert session.scalar_calls > 0
    assert blobs.keys == ["readiness-probe"]


async def test_storage_exception_is_reported_without_mutation() -> None:
    class FailingBlobs(ReadOnlyBlobs):
        async def exists(self, key: str) -> bool:
            raise BlobStorageError("storage down")

    settings = production_settings()
    deployment = DeploymentDiagnosticsService(settings, migration_head=lambda: "head")
    report = await StartupPreflightService(
        settings,
        deployment=deployment,
        migration=MigrationCompatibilityService(FakeGraph()),
    ).collect(
        ReadOnlySession(),  # type: ignore[arg-type]
        FailingBlobs(),
    )

    assert levels(report)["storage"] is Level.ERROR
