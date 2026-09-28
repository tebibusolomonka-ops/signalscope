"""The structured model smoke check, with a fake in place of GLiNER2. Nothing is downloaded."""

import io
import sys
from pathlib import Path
from typing import Any

import pytest

from signalscope.cli import build_parser, check_structured_model, main
from signalscope.core.settings import Settings
from signalscope.extraction.gliner2 import Gliner2StructuredBackend

pytestmark = pytest.mark.anyio


class FakeExtractor:
    def __init__(self, records: Any = None, relations: Any = None) -> None:
        self.records = {"event": []} if records is None else records
        self.relations = {"relation_extraction": {}} if relations is None else relations
        self.calls: list[str] = []

    def extract_json(self, text: str, schema: dict[str, list[str]]) -> Any:
        self.calls.append("json")
        return self.records

    def extract_relations(self, text: str, relation_types: dict[str, str]) -> Any:
        self.calls.append("relations")
        return self.relations


def backend_for(extractor: FakeExtractor) -> Gliner2StructuredBackend:
    def load(model: str, device: str, cache_dir: Path | None) -> FakeExtractor:
        return extractor

    return Gliner2StructuredBackend(loader=load)


async def run(
    backend: Gliner2StructuredBackend | None, settings: Settings | None = None
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await check_structured_model(settings or Settings(), out, err, backend=backend)
    return code, out.getvalue(), err.getvalue()


def test_arguments() -> None:
    assert build_parser().parse_args(["check-structured-model"]).command == (
        "check-structured-model"
    )


async def test_both_operations_run() -> None:
    extractor = FakeExtractor(
        records={"event": [{"title": "wind farm opened"}]},
        relations={"relation_extraction": {"works_for": [("Maria Lopes", "Northwind Energy")]}},
    )

    code, out, err = await run(backend_for(extractor))

    assert (code, err) == (0, "")
    assert out == (
        "Provider: gliner2\n"
        "Model: fastino/gliner2.5-multi-v1\n"
        "Structured extraction: ok\n"
        "Relation extraction: ok\n"
    )
    assert extractor.calls == ["json", "relations"]


@pytest.mark.parametrize(
    ("extractor", "message"),
    [
        (FakeExtractor(records={"records": []}), "no list of records"),
        (FakeExtractor(records=["not", "an", "object"]), "not an object"),
        (FakeExtractor(relations={"relations": []}), "no relations object"),
    ],
    ids=["records missing", "records not an object", "relations missing"],
)
async def test_bad_response_fails(extractor: FakeExtractor, message: str) -> None:
    code, out, err = await run(backend_for(extractor))

    assert (code, out) == (1, "")
    assert message in err


async def test_needs_local_structured_extraction() -> None:
    code, out, err = await run(None)

    assert (code, out) == (1, "")
    assert "SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED=true" in err


async def test_needs_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "gliner2", None)

    code, _, err = await run(None, Settings(local_structured_enabled=True))

    assert code == 1
    assert 'pip install -e ".[local-structured]"' in err


def test_main_needs_local_structured_extraction(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED", raising=False)

    assert main(["check-structured-model"]) == 1
    assert "SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED=true" in capsys.readouterr().err
