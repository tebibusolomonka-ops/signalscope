import sys

import pytest
from sqlalchemy.exc import OperationalError

from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.readiness import (
    ComponentState,
    DependencyReadinessService,
)
from signalscope.storage.blob import BlobStorageError

pytestmark = pytest.mark.anyio


class FakeSession:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails

    async def execute(self, _statement: object) -> object:
        self._maybe_fail()
        return object()

    async def scalar(self, _statement: object) -> int:
        self._maybe_fail()
        return 0

    def _maybe_fail(self) -> None:
        if self.fails:
            raise OperationalError("SELECT 1", {}, Exception("no connection"))


class FakeBlobs:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails
        self.checked: list[str] = []

    async def exists(self, key: str) -> bool:
        if self.fails:
            raise BlobStorageError("storage down")
        self.checked.append(key)
        return False


def states(report: object) -> dict[str, ComponentState]:
    return {component.name: component.state for component in report.components}  # type: ignore[attr-defined]


async def test_all_dependencies_ready() -> None:
    service = DependencyReadinessService(
        FakeSession(), Settings(), FakeBlobs(), dependency_version=lambda _name: "1.0"
    )

    report = await service.check()

    assert report.ready is True
    result = states(report)
    assert result["database"] is ComponentState.READY
    assert result["storage"] is ComponentState.READY
    assert result["scheduler"] is ComponentState.READY
    assert result["queue"] is ComponentState.READY


async def test_database_unavailable_is_not_ready() -> None:
    service = DependencyReadinessService(
        FakeSession(fails=True), Settings(), FakeBlobs(), dependency_version=lambda _name: "1.0"
    )

    report = await service.check()

    assert report.ready is False
    result = states(report)
    assert result["database"] is ComponentState.UNAVAILABLE
    assert result["scheduler"] is ComponentState.UNAVAILABLE
    assert result["queue"] is ComponentState.UNAVAILABLE


async def test_storage_not_configured_is_unavailable() -> None:
    service = DependencyReadinessService(
        FakeSession(), Settings(), None, dependency_version=lambda _name: "1.0"
    )

    report = await service.check()

    assert report.ready is False
    assert states(report)["storage"] is ComponentState.UNAVAILABLE


async def test_storage_backend_failure_is_unavailable() -> None:
    service = DependencyReadinessService(
        FakeSession(), Settings(), FakeBlobs(fails=True), dependency_version=lambda _name: "1.0"
    )

    report = await service.check()

    assert states(report)["storage"] is ComponentState.UNAVAILABLE


async def test_configured_model_without_dependency_is_degraded_not_fatal() -> None:
    settings = Settings(local_entities_enabled=True)
    service = DependencyReadinessService(
        FakeSession(), settings, FakeBlobs(), dependency_version=lambda _name: None
    )

    report = await service.check()

    # A missing model dependency never blocks readiness.
    assert report.ready is True
    assert states(report)["model_entities"] is ComponentState.DEGRADED


async def test_unconfigured_models_are_ready() -> None:
    service = DependencyReadinessService(
        FakeSession(), Settings(), FakeBlobs(), dependency_version=lambda _name: None
    )

    assert states(await service.check())["model_embeddings"] is ComponentState.READY


async def test_check_never_imports_model_packages() -> None:
    before = {name for name in sys.modules if name in {"torch", "sentence_transformers", "gliner"}}
    seen: list[str] = []

    def record(distribution: str) -> str | None:
        seen.append(distribution)
        return None

    settings = Settings(
        local_embeddings_enabled=True, local_entities_enabled=True, local_answers_enabled=True
    )
    service = DependencyReadinessService(
        FakeSession(), settings, FakeBlobs(), dependency_version=record
    )

    await service.check()

    # Only the injected metadata lookup ran; no model package was imported.
    assert seen
    after = {name for name in sys.modules if name in {"torch", "sentence_transformers", "gliner"}}
    assert after == before
