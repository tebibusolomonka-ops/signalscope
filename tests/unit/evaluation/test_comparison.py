import json
from pathlib import Path

import pytest

from signalscope.evaluation.comparison import compare_evaluation_reports, format_comparison


def _write(path: Path, *, task: str = "reranking", fingerprint: str = "a" * 64, score=0.7):
    path.write_text(
        json.dumps(
            {
                "report_version": 1,
                "task": task,
                "dataset": {"name": "fixed", "fingerprint": fingerprint},
                "metrics": {"precision": score, "optional": 1.0},
                "timings": {"wall_seconds": 2.0},
            }
        ),
        encoding="utf-8",
    )


def test_compares_factual_differences_and_ignores_missing_optional_metric(tmp_path: Path) -> None:
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    _write(old)
    _write(new, score=0.78)
    raw = json.loads(new.read_text(encoding="utf-8"))
    del raw["metrics"]["optional"]
    new.write_text(json.dumps(raw), encoding="utf-8")

    result = compare_evaluation_reports([old, new])

    assert result.metrics == {"precision": (0.7, 0.78)}
    assert "delta +0.08" in format_comparison(result)
    assert result.to_dict()["metrics"]["precision"]["deltas"][1] == pytest.approx(0.08)


def test_refuses_different_dataset(tmp_path: Path) -> None:
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    _write(first)
    _write(second, fingerprint="b" * 64)
    with pytest.raises(ValueError, match="different datasets"):
        compare_evaluation_reports([first, second])


def test_refuses_different_task(tmp_path: Path) -> None:
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    _write(first)
    _write(second, task="answer_citation")
    with pytest.raises(ValueError, match="different tasks"):
        compare_evaluation_reports([first, second])
