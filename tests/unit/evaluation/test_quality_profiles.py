import json
from pathlib import Path

import pytest

from signalscope.evaluation.quality_profiles import (
    check_evaluation_report,
    load_quality_gate_profile,
)


def _profile(tmp_path: Path, task: str = "structured_extraction"):
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps({"profile_version": 1, "task": task, "minimums": {"events.f1": 0.8}}),
        encoding="utf-8",
    )
    return load_quality_gate_profile(path)


def test_quality_gate_passes(tmp_path: Path) -> None:
    result = check_evaluation_report(
        {"task": "structured_extraction", "metrics": {"events": {"f1": 0.9}}},
        _profile(tmp_path),
    )
    assert result.passed is True


def test_quality_gate_reports_failure(tmp_path: Path) -> None:
    result = check_evaluation_report(
        {"task": "structured_extraction", "metrics": {"events": {"f1": 0.7}}},
        _profile(tmp_path),
    )
    assert result.passed is False


def test_undefined_metric_misses_requirement(tmp_path: Path) -> None:
    result = check_evaluation_report(
        {"task": "structured_extraction", "metrics": {}}, _profile(tmp_path)
    )
    assert result.requirements["events.f1"]["actual"] is None
    assert result.passed is False


def test_task_mismatch_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not match"):
        check_evaluation_report(
            {"task": "reranking", "metrics": {"events": {"f1": 1.0}}},
            _profile(tmp_path),
        )
