import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalscope.evaluation.dataset import EvaluationDataError

MICRO_REQUIREMENTS = {
    "minimum_micro_precision": "micro_precision",
    "minimum_micro_recall": "micro_recall",
    "minimum_micro_f1": "micro_f1",
    "minimum_support": "reference_triple_count",
}
TYPE_REQUIREMENTS = {
    "minimum_precision": "precision",
    "minimum_recall": "recall",
    "minimum_f1": "f1",
    "minimum_support": "support",
}


@dataclass(frozen=True, slots=True)
class RelationReadinessProfile:
    profile_version: int
    requirements: dict[str, float]
    per_type: dict[str, dict[str, float]]


@dataclass(frozen=True, slots=True)
class RelationRequirementResult:
    metric: str
    required: float
    actual: float | None
    met: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "required": self.required,
            "actual": self.actual,
            "met": self.met,
        }


def load_relation_readiness_profile(path: Path) -> RelationReadinessProfile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["profile_version"] != 1:
            raise TypeError
        requirements = _requirements(raw.get("requirements", {}), MICRO_REQUIREMENTS)
        raw_types = raw.get("per_type", {})
        if not isinstance(raw_types, dict):
            raise TypeError
        per_type = {
            name: _requirements(values, TYPE_REQUIREMENTS) for name, values in raw_types.items()
        }
        if not requirements and not per_type:
            raise TypeError
        return RelationReadinessProfile(1, requirements, per_type)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise EvaluationDataError(f"Relation readiness profile {path} is not valid.") from None


def check_relation_readiness(
    report: dict[str, Any], profile: RelationReadinessProfile
) -> tuple[RelationRequirementResult, ...]:
    if report.get("task") != "relation_evaluation":
        raise ValueError("Report task is not relation_evaluation.")
    results = []
    for requirement, required in profile.requirements.items():
        metric = MICRO_REQUIREMENTS[requirement]
        results.append(_result(metric, required, report.get(metric), missing_is_error=True))
    per_type = report.get("per_type")
    if not isinstance(per_type, dict):
        raise EvaluationDataError("Relation report per_type metrics are missing.")
    for relation_type in sorted(profile.per_type):
        metrics = per_type.get(relation_type)
        for requirement, required in profile.per_type[relation_type].items():
            metric = TYPE_REQUIREMENTS[requirement]
            actual = metrics.get(metric) if isinstance(metrics, dict) else None
            results.append(_result(f"per_type.{relation_type}.{metric}", required, actual))
    return tuple(results)


def format_relation_readiness(results: tuple[RelationRequirementResult, ...]) -> str:
    lines = []
    for result in results:
        actual = "missing" if result.actual is None else f"{result.actual:g}"
        lines.append(
            f"{result.metric}: required {result.required:g}, actual {actual}, "
            f"met {'yes' if result.met else 'no'}"
        )
    return "\n".join(lines) + "\n"


def _result(
    metric: str, required: float, actual: Any, *, missing_is_error: bool = False
) -> RelationRequirementResult:
    if actual is None and missing_is_error:
        raise EvaluationDataError(f"Relation report metric {metric} is missing.")
    if actual is not None and (isinstance(actual, bool) or not isinstance(actual, (int, float))):
        raise EvaluationDataError(f"Relation report metric {metric} is not numeric.")
    value = None if actual is None else float(actual)
    return RelationRequirementResult(
        metric, required, value, value is not None and value >= required
    )


def _requirements(raw: Any, allowed: dict[str, str]) -> dict[str, float]:
    if not isinstance(raw, dict) or any(name not in allowed for name in raw):
        raise TypeError
    result = {}
    for name, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise TypeError
        result[name] = float(value)
    return result
