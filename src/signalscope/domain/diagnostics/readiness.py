import importlib.metadata
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.settings import Settings
from signalscope.domain.ingestion.model import IngestionJob
from signalscope.domain.organizations.backup_policy import OrganizationBackupPolicy
from signalscope.storage.blob import BlobStorageError, BlobStore

DependencyVersion = Callable[[str], str | None]

# Each local model capability and the installed package it needs to run.
MODEL_DEPENDENCIES = (
    ("embeddings", "local_embeddings_enabled", "sentence-transformers"),
    ("reranking", "local_reranking_enabled", "sentence-transformers"),
    ("entities", "local_entities_enabled", "gliner"),
    ("structured_extraction", "local_structured_enabled", "gliner2"),
    ("answers", "local_answers_enabled", "transformers"),
)


class ComponentState(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ComponentReadiness:
    name: str
    state: ComponentState
    required: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    components: tuple[ComponentReadiness, ...]

    @property
    def ready(self) -> bool:
        """True unless a required component is unavailable. Degraded still serves."""
        return not any(
            component.required and component.state is ComponentState.UNAVAILABLE
            for component in self.components
        )


class DependencyReadinessService:
    """Factual production dependency checks.

    It reports whether the database, file storage, scheduler and queues answer,
    and whether configured local models have their dependencies installed. It
    never loads or downloads a model and never reaches the public network.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        blobs: BlobStore | None,
        *,
        dependency_version: DependencyVersion | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.blobs = blobs
        self.dependency_version = dependency_version or _installed_version

    async def check(self) -> ReadinessReport:
        components = [
            await self._database(),
            await self._storage(),
            await self._scheduler(),
            await self._queue(),
            *self._models(),
        ]
        return ReadinessReport(components=tuple(components))

    async def _database(self) -> ComponentReadiness:
        try:
            await self.session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return ComponentReadiness(
                "database", ComponentState.UNAVAILABLE, True, "The database did not answer."
            )
        return ComponentReadiness("database", ComponentState.READY, True, "The database answered.")

    async def _storage(self) -> ComponentReadiness:
        if self.blobs is None:
            return ComponentReadiness(
                "storage", ComponentState.UNAVAILABLE, True, "File storage is not configured."
            )
        try:
            await self.blobs.exists("readiness-probe")
        except BlobStorageError:
            return ComponentReadiness(
                "storage", ComponentState.UNAVAILABLE, True, "File storage did not answer."
            )
        return ComponentReadiness("storage", ComponentState.READY, True, "File storage answered.")

    async def _scheduler(self) -> ComponentReadiness:
        try:
            await self.session.scalar(select(func.count()).select_from(OrganizationBackupPolicy))
        except SQLAlchemyError:
            return ComponentReadiness(
                "scheduler",
                ComponentState.UNAVAILABLE,
                True,
                "The scheduler could not read its policies.",
            )
        return ComponentReadiness(
            "scheduler", ComponentState.READY, True, "The scheduler can read its policies."
        )

    async def _queue(self) -> ComponentReadiness:
        try:
            await self.session.scalar(select(func.count()).select_from(IngestionJob))
        except SQLAlchemyError:
            return ComponentReadiness(
                "queue", ComponentState.UNAVAILABLE, True, "The job queue could not be queried."
            )
        return ComponentReadiness(
            "queue", ComponentState.READY, True, "The job queue can be queried."
        )

    def _models(self) -> list[ComponentReadiness]:
        results: list[ComponentReadiness] = []
        for name, flag, distribution in MODEL_DEPENDENCIES:
            component = f"model_{name}"
            if not getattr(self.settings, flag):
                results.append(
                    ComponentReadiness(component, ComponentState.READY, False, "Not configured.")
                )
                continue
            if self.dependency_version(distribution) is not None:
                results.append(
                    ComponentReadiness(
                        component,
                        ComponentState.READY,
                        False,
                        "Configured; dependency available.",
                    )
                )
            else:
                results.append(
                    ComponentReadiness(
                        component,
                        ComponentState.DEGRADED,
                        False,
                        "Configured; dependency unavailable.",
                    )
                )
        return results


def _installed_version(distribution: str) -> str | None:
    """Return an installed package version, or None. It never imports the package."""
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None
