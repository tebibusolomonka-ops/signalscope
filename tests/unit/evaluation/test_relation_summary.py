import json
from io import StringIO
from pathlib import Path

from signalscope.cli import relation_evaluation_summary_command
from signalscope.evaluation.relation_summary import (
    format_relation_summary,
    relation_evaluation_summary,
)


def report():
    return {
        "task": "relation_evaluation",
        "dataset": {"name": "relations", "version": "1", "fingerprint": "a" * 64},
        "model": "fake-model",
        "provider": "fake",
        "records_evaluated": 2,
        "reference_triple_count": 2,
        "predicted_triple_count": 1,
        "micro_precision": 1.0,
        "micro_recall": 0.5,
        "micro_f1": 2 / 3,
        "per_type": {"works_for": {"support": 1, "precision": 1.0, "recall": 1.0, "f1": 1.0}},
    }


def test_summary_without_confidence_includes_limitations() -> None:
    summary = relation_evaluation_summary(report())
    text = format_relation_summary(summary)
    assert summary["confidence"]["available"] is False
    assert "exact deterministic matching" in " ".join(summary["limitations"])
    assert "Confidence was not provided" in text
    assert "persist" not in text.lower()


def test_summary_with_confidence_and_readiness_is_json_compatible() -> None:
    summary = relation_evaluation_summary(
        report(),
        confidence={"confidence_available": True, "buckets": [{"lower": 0.0}]},
        readiness={
            "requirements": [
                {"metric": "micro_precision", "required": 0.8, "actual": 1.0, "met": True},
                {"metric": "micro_recall", "required": 0.8, "actual": 0.5, "met": False},
            ]
        },
    )
    assert len(summary["requirements"]["met"]) == 1
    assert len(summary["requirements"]["missed"]) == 1
    assert summary["confidence"]["buckets"] == [{"lower": 0.0}]


def test_cli_writes_json_summary(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report()), encoding="utf-8")
    out = StringIO()
    assert relation_evaluation_summary_command(path, json_output=True, out=out) == 0
    assert json.loads(out.getvalue())["task"] == "relation_evaluation_summary"
