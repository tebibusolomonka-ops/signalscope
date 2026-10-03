import json
from pathlib import Path

import pytest

from signalscope.evaluation.dataset import EvaluationDataError
from signalscope.evaluation.relation_readiness import (
    check_relation_readiness,
    load_relation_readiness_profile,
)


def profile(tmp_path: Path, requirements=None, per_type=None):
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "profile_version": 1,
                "requirements": requirements or {"minimum_micro_precision": 0.8},
                "per_type": per_type or {},
            }
        )
    )
    return load_relation_readiness_profile(path)


def report():
    return {
        "task": "relation_evaluation",
        "micro_precision": 0.9,
        "micro_recall": 0.8,
        "micro_f1": 0.85,
        "reference_triple_count": 10,
        "per_type": {"works_for": {"precision": 1.0, "recall": 0.5, "f1": 2 / 3, "support": 2}},
    }


@pytest.mark.parametrize(
    ("requirement", "value"),
    [
        ("minimum_micro_precision", 0.95),
        ("minimum_micro_recall", 0.9),
        ("minimum_micro_f1", 0.9),
        ("minimum_support", 11),
    ],
)
def test_micro_requirement_failure(tmp_path: Path, requirement: str, value: float) -> None:
    result = check_relation_readiness(report(), profile(tmp_path, {requirement: value}))
    assert result[0].met is False


def test_all_pass_and_per_type_failure(tmp_path: Path) -> None:
    passing = check_relation_readiness(report(), profile(tmp_path))
    failing = check_relation_readiness(
        report(), profile(tmp_path, per_type={"works_for": {"minimum_recall": 0.8}})
    )
    assert all(item.met for item in passing)
    assert failing[-1].met is False


def test_missing_relation_type_is_missed(tmp_path: Path) -> None:
    result = check_relation_readiness(
        report(), profile(tmp_path, per_type={"owns": {"minimum_support": 1}})
    )
    assert result[-1].actual is None and result[-1].met is False


def test_missing_metric_and_wrong_task_are_rejected(tmp_path: Path) -> None:
    broken = report()
    del broken["micro_precision"]
    with pytest.raises(EvaluationDataError, match="missing"):
        check_relation_readiness(broken, profile(tmp_path))
    with pytest.raises(ValueError, match="not relation_evaluation"):
        check_relation_readiness({"task": "reranking"}, profile(tmp_path))
