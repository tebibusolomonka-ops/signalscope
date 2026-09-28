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

    def extract_relations(self, text: str, relation_types: dict[str, str]) -> Any:
        self.calls.append((text, relation_types))
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


# The options AutoExtractor.from_pretrained accepts in gliner2 2.0. It raises
# TypeError for any other keyword.
GLINER2_LOAD_OPTIONS = {
    "cache_dir",
    "force_download",
    "local_files_only",
    "token",
    "revision",
    "subfolder",
    "proxies",
    "quantize",
    "compile",
    "map_location",
    "use_flashdeberta",
    "word_splitter",
}


class FakeLibraries:
    """Stand-ins for gliner2 and huggingface_hub that record calls. Nothing is downloaded."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.loads: list[tuple[str, dict[str, Any]]] = []
        self.snapshots: list[tuple[str, dict[str, Any]]] = []
        self.snapshot_dir = str(tmp_path / "snapshot")
        libraries = self

        class AutoExtractor:
            @staticmethod
            def from_pretrained(model: str, *args: Any, **options: Any) -> FakeAutoExtractor:
                unknown = set(options) - GLINER2_LOAD_OPTIONS
                if args or unknown:
                    raise TypeError(f"from_pretrained does not accept {sorted(unknown)}")
                libraries.loads.append((model, options))
                return FakeAutoExtractor()

        def snapshot_download(repo_id: str, **options: Any) -> str:
            libraries.snapshots.append((repo_id, options))
            return libraries.snapshot_dir

        gliner2 = types.ModuleType("gliner2")
        gliner2.AutoExtractor = AutoExtractor  # type: ignore[attr-defined]
        hub = types.ModuleType("huggingface_hub")
        hub.snapshot_download = snapshot_download  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "gliner2", gliner2)
        monkeypatch.setitem(sys.modules, "huggingface_hub", hub)


def test_loader_forwards_only_the_device(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    libraries = FakeLibraries(monkeypatch, tmp_path)

    load_gliner2("fastino/gliner2.5-multi-v1", "cuda", None)

    assert libraries.loads == [("fastino/gliner2.5-multi-v1", {"map_location": "cuda"})]
    assert libraries.snapshots == []


def test_cache_folder_holds_the_whole_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    libraries = FakeLibraries(monkeypatch, tmp_path)

    load_gliner2("fastino/gliner2.5-multi-v1", "cpu", tmp_path / "models")

    # AutoExtractor would use cache_dir for the config file only, so the model is
    # downloaded into the cache first and loaded from there.
    assert libraries.snapshots == [
        ("fastino/gliner2.5-multi-v1", {"cache_dir": str(tmp_path / "models")})
    ]
    assert libraries.loads == [(libraries.snapshot_dir, {"map_location": "cpu"})]


def test_missing_hub_library_gives_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    FakeLibraries(monkeypatch, tmp_path)
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)

    with pytest.raises(LocalStructuredNotInstalledError):
        load_gliner2("fastino/gliner2.5-multi-v1", "cpu", None)


async def test_backend_loads_lazily_through_the_loader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    libraries = FakeLibraries(monkeypatch, tmp_path)
    backend = Gliner2StructuredBackend(device="cpu")

    assert libraries.loads == []
    await backend.extract_json(TEXT, SCHEMA)
    await backend.extract_json(TEXT, SCHEMA)

    assert libraries.loads == [("fastino/gliner2.5-multi-v1", {"map_location": "cpu"})]


async def test_relations_are_forwarded_off_the_event_loop() -> None:
    output = {"relation_extraction": {"works_for": [("Ana", "Acme")]}}
    extractor = FakeAutoExtractor(output)
    backend, loader = backend_with(extractor)

    found = await backend.extract_relations("Ana works for Acme.", {"works_for": "Employment"})

    assert found == output
    assert extractor.calls == [("Ana works for Acme.", {"works_for": "Employment"})]
    assert extractor.threads != [threading.current_thread().name]
    assert len(loader.calls) == 1


async def test_relation_output_that_is_not_an_object_is_rejected() -> None:
    backend, _ = backend_with(FakeAutoExtractor(["works_for"]))

    with pytest.raises(InvalidStructuredOutputError):
        await backend.extract_relations("Ana works for Acme.", {"works_for": "Employment"})
