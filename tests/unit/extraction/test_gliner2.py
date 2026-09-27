"""The GLiNER2 backend, with a fake in place of the real model.

Nothing here downloads or loads model files.
"""

import asyncio
import sys
import threading
import types
from pathlib import Path
from typing import Any

import pytest

from signalscope.core.errors import ServiceUnavailableError
from signalscope.extraction.gliner2 import (
    Gliner2StructuredBackend,
    InvalidStructuredOutputError,
    LocalStructuredNotInstalledError,
    load_gliner2,
)

pytestmark = pytest.mark.anyio

TEXT = "The river flooded the town on 3 March 2026."
SCHEMA = {"event": ("event_type::str", "title::str::What happened")}


class FakeAutoExtractor:
    """Returns a fixed answer and records how it was called."""

    def __init__(self, output: Any = None) -> None:
        self.output = {"event": [{"title": "Town flooded"}]} if output is None else output
        self.calls: list[tuple[str, Any]] = []
        self.threads: list[str] = []

    def extract_json(self, text: str, schema: dict[str, list[str]]) -> Any:
        self.calls.append((text, schema))
        self.threads.append(threading.current_thread().name)
        return self.output


class FakeLoader:
    def __init__(self, extractor: FakeAutoExtractor) -> None:
        self.extractor = extractor
        self.calls: list[tuple[str, str, Path | None]] = []

    def __call__(self, model: str, device: str, cache_dir: Path | None) -> FakeAutoExtractor:
        self.calls.append((model, device, cache_dir))
        return self.extractor


def backend_with(
    extractor: FakeAutoExtractor | None = None, **options: Any
) -> tuple[Gliner2StructuredBackend, FakeLoader]:
    loader = FakeLoader(extractor or FakeAutoExtractor())
    return Gliner2StructuredBackend(loader=loader, **options), loader


def test_identity_and_defaults() -> None:
    backend, loader = backend_with()

    assert (backend.provider_name, backend.model_name) == ("gliner2", "fastino/gliner2.5-multi-v1")
    assert (backend.device, backend.cache_dir) == ("cpu", None)
    assert loader.calls == []


async def test_model_is_loaded_lazily_once_with_the_device(tmp_path: Path) -> None:
    backend, loader = backend_with(device="cuda", cache_dir=tmp_path)

    await asyncio.gather(*(backend.extract_json(TEXT, SCHEMA) for _ in range(4)))
    await backend.extract_json("Another text.", SCHEMA)

    assert loader.calls == [("fastino/gliner2.5-multi-v1", "cuda", tmp_path)]


async def test_request_is_forwarded_and_output_returned() -> None:
    extractor = FakeAutoExtractor()
    backend, _ = backend_with(extractor)

    output = await backend.extract_json(TEXT, SCHEMA)

    assert output == {"event": [{"title": "Town flooded"}]}
    assert extractor.calls == [(TEXT, {"event": ["event_type::str", "title::str::What happened"]})]


async def test_model_runs_off_the_event_loop_thread() -> None:
    extractor = FakeAutoExtractor()
    backend, _ = backend_with(extractor)

    await backend.extract_json(TEXT, SCHEMA)

    assert extractor.threads != [threading.current_thread().name]


async def test_output_that_is_not_an_object_is_rejected() -> None:
    backend, _ = backend_with(FakeAutoExtractor(["not", "an", "object"]))

    with pytest.raises(InvalidStructuredOutputError):
        await backend.extract_json(TEXT, SCHEMA)


def test_missing_library_gives_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # None in sys.modules makes the import fail, as if the extra were not installed.
    monkeypatch.setitem(sys.modules, "gliner2", None)

    with pytest.raises(LocalStructuredNotInstalledError, match="local-structured") as error:
        load_gliner2("fastino/gliner2.5-multi-v1", "cpu", None)

    assert isinstance(error.value, ServiceUnavailableError)


async def test_missing_library_surfaces_on_first_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "gliner2", None)

    with pytest.raises(LocalStructuredNotInstalledError):
        await Gliner2StructuredBackend().extract_json(TEXT, SCHEMA)


def test_loader_uses_auto_extractor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class AutoExtractor:
        @staticmethod
        def from_pretrained(model: str, **options: Any) -> FakeAutoExtractor:
            calls.append((model, options))
            return FakeAutoExtractor()

    # A stand-in for the library, so nothing is downloaded.
    module = types.ModuleType("gliner2")
    module.AutoExtractor = AutoExtractor  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gliner2", module)

    load_gliner2("fastino/gliner2.5-multi-v1", "cpu", None)
    load_gliner2("fastino/gliner2.5-multi-v1", "cuda", tmp_path)

    assert calls == [
        ("fastino/gliner2.5-multi-v1", {"map_location": "cpu"}),
        ("fastino/gliner2.5-multi-v1", {"map_location": "cuda", "cache_dir": tmp_path}),
    ]
