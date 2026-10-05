import pytest
from sqlalchemy.exc import OperationalError

from signalscope.domain.diagnostics.migration_compatibility import (
    AlembicRevisionGraph,
    MigrationCompatibilityService,
    MigrationCompatibilityState,
)

pytestmark = pytest.mark.anyio


class FakeGraph:
    def __init__(
        self,
        *,
        heads: tuple[str, ...] = ("head",),
        parents: dict[str, str | None] | None = None,
    ) -> None:
        self._heads = heads
        self._parents = parents or {"head": "middle", "middle": "base", "base": None}

    def heads(self) -> tuple[str, ...]:
        return self._heads

    def knows(self, revision: str) -> bool:
        return revision in self._parents

    def is_ancestor(self, older: str, newer: str) -> bool:
        current: str | None = newer
        while current is not None:
            if current == older:
                return True
            current = self._parents.get(current)
        return False


@pytest.mark.parametrize(
    ("revisions", "state"),
    [
        (("head",), MigrationCompatibilityState.CURRENT),
        (("middle",), MigrationCompatibilityState.BEHIND),
        ((), MigrationCompatibilityState.BEHIND),
        (("missing",), MigrationCompatibilityState.UNKNOWN_REVISION),
    ],
)
async def test_revision_states(
    revisions: tuple[str, ...], state: MigrationCompatibilityState
) -> None:
    report = MigrationCompatibilityService(FakeGraph()).analyze(revisions)

    assert report.state is state


async def test_database_ahead_of_application() -> None:
    graph = FakeGraph(
        heads=("middle",),
        parents={"future": "middle", "middle": "base", "base": None},
    )

    report = MigrationCompatibilityService(graph).analyze(("future",))

    assert report.state is MigrationCompatibilityState.DATABASE_AHEAD


@pytest.mark.parametrize(
    ("heads", "revisions"),
    [(("left", "right"), ("left",)), (("head",), ("left", "right"))],
)
async def test_multiple_heads(heads: tuple[str, ...], revisions: tuple[str, ...]) -> None:
    report = MigrationCompatibilityService(FakeGraph(heads=heads)).analyze(revisions)

    assert report.state is MigrationCompatibilityState.MULTIPLE_HEADS


class FailedScalars:
    async def scalars(self, _statement: object) -> object:
        raise OperationalError("SELECT", {}, Exception("database down"))


async def test_database_unavailable() -> None:
    report = await MigrationCompatibilityService(FakeGraph()).check(  # type: ignore[arg-type]
        FailedScalars()
    )

    assert report.state is MigrationCompatibilityState.DATABASE_UNAVAILABLE


async def test_real_alembic_graph_has_one_known_head() -> None:
    graph = AlembicRevisionGraph()

    assert len(graph.heads()) == 1
    assert graph.knows(graph.heads()[0]) is True
