"""The evaluate-extraction command, with fake providers. No model is loaded."""

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from signalscope.claims.provider import ExtractedClaim
from signalscope.cli import build_parser, evaluate_extraction, main
from signalscope.core.settings import Settings
from signalscope.events.provider import ExtractedEvent
from signalscope.relations.provider import ExtractedRelation

pytestmark = pytest.mark.anyio

TEXT = "Ana Silva works for Acme. Prices rose 5%."
DATASET = {
    "name": "media",
    "documents": [{"key": "a", "text": TEXT}],
    "events": [{"document_key": "a", "event_type": "hiring", "title": "Ana joined Acme"}],
    "claims": [
        {
            "document_key": "a",
            "claim_type": "statistic",
            "surface_text": "Prices rose 5%",
            "start_char": 26,
            "end_char": 40,
        }
    ],
    "relations": [
        {
            "document_key": "a",
            "subject_text": "Ana Silva",
            "relation_type": "works_for",
            "object_text": "Acme",
        },
        {
            "document_key": "a",
            "subject_text": "Acme",
            "relation_type": "located_in",
            "object_text": "Porto",
        },
    ],
}


class Scripted:
    provider_name = "test"
    model_name = "scripted"

    def __init__(self, answer: list[Any], error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error

    async def extract(self, text: str) -> list[Any]:
        if self.error is not None:
            raise self.error
        return self.answer


def events() -> Scripted:
    return Scripted([ExtractedEvent(event_type="hiring", title="Ana joined Acme")])


def claims() -> Scripted:
    return Scripted(
        [
            ExtractedClaim(
                text="Prices rose 5%",
                claim_type="statistic",
                surface_text="Prices rose 5%",
                start_char=26,
                end_char=40,
            ),
            ExtractedClaim(
                text="Ana works for Acme",
                claim_type="statement",
                surface_text="Ana Silva works for Acme",
                start_char=0,
                end_char=24,
            ),
        ]
    )


def relations() -> Scripted:
    return Scripted(
        [ExtractedRelation(subject_text="Ana Silva", relation_type="works_for", object_text="Acme")]
    )


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    path = tmp_path / "data.json"
    path.write_text(json.dumps(DATASET), encoding="utf-8")
    return path


async def run(path: Path, settings: Settings | None = None, **options: Any) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await evaluate_extraction(path, settings or Settings(), out, err, **options)
    return code, out.getvalue(), err.getvalue()


def test_arguments() -> None:
    args = build_parser().parse_args(["evaluate-extraction", "data.json", "--mode", "relation"])

    assert (args.command, args.dataset, args.mode, args.json_output) == (
        "evaluate-extraction",
        Path("data.json"),
        "relation",
        None,
    )


async def test_all_modes(dataset: Path) -> None:
    code, out, err = await run(
        dataset,
        event_provider=events(),
        claim_provider=claims(),
        relation_provider=relations(),
    )

    assert (code, err) == (0, "")
    assert out == (
        "Dataset: media\n"
        "Documents: 1\n"
        "\n"
        "Events\n"
        "Model: test/scripted\n"
        "Gold: 1\nPredicted: 1\nMatched: 1\n"
        "Precision: 1.000\nRecall: 1.000\nF1: 1.000\n"
        "\n"
        "Claims\n"
        "Model: test/scripted\n"
        "Gold: 1\nPredicted: 2\nMatched: 1\n"
        "Precision: 0.500\nRecall: 1.000\nF1: 0.667\n"
        "\n"
        "Relations\n"
        "Model: test/scripted\n"
        "Gold: 2\nPredicted: 1\nMatched: 1\n"
        "Precision: 1.000\nRecall: 0.500\nF1: 0.667\n"
    )


async def test_one_mode_and_json_output(dataset: Path, tmp_path: Path) -> None:
    report = tmp_path / "report.json"

    code, out, _ = await run(
        dataset, mode="relation", relation_provider=relations(), json_output=report
    )

    assert code == 0
    assert "Relations" in out and "Events" not in out and "Claims" not in out
    data = json.loads(report.read_text(encoding="utf-8"))
    assert list(data["results"]) == ["relation"]
    result = data["results"]["relation"]
    assert (result["precision"], result["recall"]) == (1.0, 0.5)
    assert result["documents"] == [
        {
            "key": "a",
            "gold_count": 2,
            "predicted_count": 1,
            "matched_count": 1,
            "missed": ["Acme located_in Porto"],
            "extra": [],
        }
    ]


async def test_undefined_values_print_as_n_a(dataset: Path) -> None:
    _, out, _ = await run(dataset, mode="event", event_provider=Scripted([]))

    assert "Precision: n/a\nRecall: 0.000\nF1: n/a\n" in out


async def test_local_models_need_structured_extraction(dataset: Path) -> None:
    code, out, err = await run(dataset, mode="claim")

    assert (code, out) == (1, "")
    assert "SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED=true" in err


async def test_local_models_need_the_extra(dataset: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "gliner2", None)

    code, _, err = await run(dataset, Settings(local_structured_enabled=True))

    assert code == 1
    assert 'pip install -e ".[local-structured]"' in err


async def test_bad_dataset(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"name": "x"}', encoding="utf-8")

    code, out, err = await run(path, event_provider=events())

    assert (code, out) == (1, "")
    assert "missing fields: documents" in err


async def test_invalid_model_output_fails(dataset: Path) -> None:
    bad = Scripted([ExtractedEvent(event_type="", title="Ana joined Acme")])

    code, out, err = await run(dataset, mode="event", event_provider=bad)

    assert (code, out) == (1, "")
    assert "without a type" in err


def test_main_needs_local_structured_extraction(
    dataset: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED", raising=False)

    assert main(["evaluate-extraction", str(dataset)]) == 1
    assert "SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED=true" in capsys.readouterr().err


def gates_file(tmp_path: Path, gates: Any) -> Path:
    path = tmp_path / "gates.json"
    path.write_text(json.dumps(gates), encoding="utf-8")
    return path


async def test_quality_gates_pass(dataset: Path, tmp_path: Path) -> None:
    gates = gates_file(tmp_path, {"event": {"precision": 1.0, "f1": 0.9}})

    code, out, _ = await run(dataset, mode="event", event_provider=events(), quality_gates=gates)

    assert code == 0
    assert out.endswith(
        "Quality gates\n"
        "Event precision: 1.000, minimum 1.000, passed\n"
        "Event f1: 1.000, minimum 0.900, passed\n"
        "Gates missed: 0 of 2\n"
    )


async def test_quality_gates_missed(dataset: Path, tmp_path: Path) -> None:
    gates = gates_file(
        tmp_path, {"claim": {"precision": 0.9, "recall": 0.5}, "relation": {"f1": 0.5}}
    )

    code, out, _ = await run(dataset, mode="claim", claim_provider=claims(), quality_gates=gates)

    assert code == 1
    assert "Claim precision: 0.500, minimum 0.900, missed\n" in out
    assert "Claim recall: 1.000, minimum 0.500, passed\n" in out
    # The relation mode did not run, so its gate cannot pass.
    assert "Relation f1: not run, minimum 0.500, missed\n" in out
    assert out.endswith("Gates missed: 2 of 3\n")
    for word in ("good", "bad", "safe", "unsafe"):
        assert word not in out.lower()


async def test_undefined_metric_misses_its_gate(dataset: Path, tmp_path: Path) -> None:
    gates = gates_file(tmp_path, {"event": {"precision": 0.0}})

    code, out, _ = await run(
        dataset, mode="event", event_provider=Scripted([]), quality_gates=gates
    )

    assert code == 1
    assert "Event precision: undefined, minimum 0.000, missed\n" in out


async def test_bad_gates_file_fails_before_any_model(dataset: Path, tmp_path: Path) -> None:
    gates = gates_file(tmp_path, {"event": {"f1": 2}})
    provider = Scripted([], error=AssertionError("the model must not run"))

    code, out, err = await run(dataset, event_provider=provider, quality_gates=gates)

    assert (code, out) == (1, "")
    assert "between 0 and 1" in err


async def test_without_gates_nothing_changes(dataset: Path) -> None:
    code, out, _ = await run(dataset, mode="event", event_provider=events())

    assert code == 0
    assert "Quality gates" not in out


def test_gates_argument() -> None:
    args = build_parser().parse_args(
        ["evaluate-extraction", "data.json", "--quality-gates", "gates.json"]
    )

    assert args.quality_gates == Path("gates.json")
