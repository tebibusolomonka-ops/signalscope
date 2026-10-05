from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


class MigrationCompatibilityState(StrEnum):
    CURRENT = "current"
    BEHIND = "behind"
    DATABASE_AHEAD = "database_ahead_of_application"
    MULTIPLE_HEADS = "multiple_heads"
    UNKNOWN_REVISION = "unknown_revision"
    DATABASE_UNAVAILABLE = "database_unavailable"


@dataclass(frozen=True, slots=True)
class MigrationCompatibilityReport:
    state: MigrationCompatibilityState
    database_revisions: tuple[str, ...]
    application_heads: tuple[str, ...]
    message: str

    @property
    def current(self) -> bool:
        return self.state is MigrationCompatibilityState.CURRENT

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "current": self.current,
            "database_revisions": list(self.database_revisions),
            "application_heads": list(self.application_heads),
            "message": self.message,
        }


class RevisionGraph(Protocol):
    def heads(self) -> tuple[str, ...]: ...

    def knows(self, revision: str) -> bool: ...

    def is_ancestor(self, older: str, newer: str) -> bool: ...


class AlembicRevisionGraph:
    def __init__(self) -> None:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        ini = Path(__file__).resolve().parents[4] / "alembic.ini"
        self._script = ScriptDirectory.from_config(Config(str(ini)))

    def heads(self) -> tuple[str, ...]:
        return tuple(sorted(self._script.get_heads()))

    def knows(self, revision: str) -> bool:
        try:
            return self._script.get_revision(revision) is not None
        except Exception:
            return False

    def is_ancestor(self, older: str, newer: str) -> bool:
        if older == newer:
            return True
        try:
            list(self._script.iterate_revisions(newer, older))
        except Exception:
            return False
        return True


class MigrationCompatibilityService:
    """Compare database revisions with the application migration graph."""

    def __init__(self, graph: RevisionGraph | None = None) -> None:
        self._graph = graph or AlembicRevisionGraph()

    async def check(self, session: AsyncSession) -> MigrationCompatibilityReport:
        try:
            result = await session.scalars(text("SELECT version_num FROM alembic_version"))
            database_revisions = tuple(sorted(result.all()))
        except SQLAlchemyError:
            return self.database_unavailable()
        return self.analyze(database_revisions)

    def database_unavailable(self) -> MigrationCompatibilityReport:
        return MigrationCompatibilityReport(
            state=MigrationCompatibilityState.DATABASE_UNAVAILABLE,
            database_revisions=(),
            application_heads=self._graph.heads(),
            message="Database migration state could not be read.",
        )

    def analyze(self, database_revisions: tuple[str, ...]) -> MigrationCompatibilityReport:
        application_heads = self._graph.heads()
        if len(application_heads) != 1 or len(database_revisions) > 1:
            return MigrationCompatibilityReport(
                MigrationCompatibilityState.MULTIPLE_HEADS,
                database_revisions,
                application_heads,
                "Migration state has multiple heads.",
            )
        if not application_heads:
            return MigrationCompatibilityReport(
                MigrationCompatibilityState.UNKNOWN_REVISION,
                database_revisions,
                application_heads,
                "Application migration head could not be determined.",
            )
        application_head = application_heads[0]
        if not database_revisions:
            return MigrationCompatibilityReport(
                MigrationCompatibilityState.BEHIND,
                database_revisions,
                application_heads,
                "Database has no migration revision.",
            )
        database_revision = database_revisions[0]
        if database_revision == application_head:
            return MigrationCompatibilityReport(
                MigrationCompatibilityState.CURRENT,
                database_revisions,
                application_heads,
                "Database migration is current.",
            )
        if not self._graph.knows(database_revision):
            return MigrationCompatibilityReport(
                MigrationCompatibilityState.UNKNOWN_REVISION,
                database_revisions,
                application_heads,
                "Database revision is not known to this application.",
            )
        if self._graph.is_ancestor(database_revision, application_head):
            state = MigrationCompatibilityState.BEHIND
            message = "Database migration is behind the application."
        elif self._graph.is_ancestor(application_head, database_revision):
            state = MigrationCompatibilityState.DATABASE_AHEAD
            message = "Database migration is ahead of the application."
        else:
            state = MigrationCompatibilityState.UNKNOWN_REVISION
            message = "Database revision is not on the application migration line."
        return MigrationCompatibilityReport(state, database_revisions, application_heads, message)
