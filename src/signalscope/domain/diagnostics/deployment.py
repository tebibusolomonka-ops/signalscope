from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.production_config import (
    ConfigValidationResult,
    ProductionConfigurationValidator,
)
from signalscope.domain.diagnostics.queue_readiness import (
    QueueObservation,
    QueueReadinessService,
)
from signalscope.domain.diagnostics.readiness import (
    DependencyReadinessService,
    ReadinessReport,
)
from signalscope.evaluation.model_environment import model_environment_report
from signalscope.storage.blob import BlobStore

MigrationHead = Callable[[], str | None]


@dataclass(frozen=True, slots=True)
class DeploymentReport:
    environment: dict[str, Any]
    production_config: ConfigValidationResult
    readiness: ReadinessReport | None
    queues: tuple[QueueObservation, ...]
    migration_current: str | None
    migration_head: str | None

    @property
    def migration_up_to_date(self) -> bool:
        return self.migration_current is not None and self.migration_current == self.migration_head

    @property
    def healthy(self) -> bool:
        if self.production_config.has_errors:
            return False
        if self.readiness is not None and not self.readiness.ready:
            return False
        return self.migration_current is None or self.migration_up_to_date

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "environment": self.environment,
            "production_config": [
                {"check": f.check, "level": f.level.value, "message": f.message}
                for f in self.production_config.findings
            ],
            "readiness": None
            if self.readiness is None
            else {
                "ready": self.readiness.ready,
                "components": [
                    {
                        "name": c.name,
                        "state": c.state.value,
                        "required": c.required,
                        "detail": c.detail,
                    }
                    for c in self.readiness.components
                ],
            },
            "queues": [
                {
                    "queue": q.queue,
                    "query_available": q.query_available,
                    "waiting": q.waiting,
                    "running": q.running,
                    "oldest_waiting_age_seconds": q.oldest_waiting_age_seconds,
                    "expired_leases": q.expired_leases,
                }
                for q in self.queues
            ],
            "migration": {
                "current": self.migration_current,
                "head": self.migration_head,
                "up_to_date": self.migration_up_to_date,
            },
        }


class DeploymentDiagnosticsService:
    """Assemble read-only deployment facts.

    It never runs migrations, changes queues, loads a model or reaches the
    network, and it prints no secrets.
    """

    def __init__(self, settings: Settings, *, migration_head: MigrationHead | None = None) -> None:
        self.settings = settings
        self.migration_head = migration_head or alembic_migration_head

    def without_database(self) -> DeploymentReport:
        """Diagnostics when no database is configured."""
        return DeploymentReport(
            environment=model_environment_report().to_dict(),
            production_config=ProductionConfigurationValidator(self.settings).validate(),
            readiness=None,
            queues=(),
            migration_current=None,
            migration_head=self.migration_head(),
        )

    async def collect(self, session: AsyncSession, blobs: BlobStore | None) -> DeploymentReport:
        readiness = await DependencyReadinessService(session, self.settings, blobs).check()
        queues = await QueueReadinessService(session).observe()
        return DeploymentReport(
            environment=model_environment_report().to_dict(),
            production_config=ProductionConfigurationValidator(self.settings).validate(),
            readiness=readiness,
            queues=queues.queues,
            migration_current=await _migration_current(session),
            migration_head=self.migration_head(),
        )


async def _migration_current(session: AsyncSession) -> str | None:
    try:
        current: str | None = await session.scalar(text("SELECT version_num FROM alembic_version"))
    except SQLAlchemyError:
        return None
    return current


def alembic_migration_head() -> str | None:
    """The newest migration in the code, read without touching the database."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        ini = Path(__file__).resolve().parents[4] / "alembic.ini"
        return ScriptDirectory.from_config(Config(str(ini))).get_current_head()
    except Exception:
        return None
