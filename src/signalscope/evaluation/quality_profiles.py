import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalscope.evaluation.dataset import EvaluationDataError


@dataclass(frozen=True, slots=True)
class QualityGateProfile:
    profile_version: int
    task: str
    minimums: dict[str, float]


@dataclass(frozen=True, slots=True)
class QualityGateResult:
    passed: bool
    requirements: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "requirements": self.requirements}


def load_quality_gate_profile(path: Path) -> QualityGateProfile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        minimums = raw["minimums"]
        if raw["profile_version"] != 1 or not isinstance(raw["task"], str):
            raise TypeError
        if not isinstance(minimums, dict) or not minimums:
            raise TypeError
        if any(
            not isinstance(name, str)
            or not name
            or not isinstance(value, (int, float))
            or isinstance(value, bool)
            for name, value in minimums.items()
        ):
            raise TypeError
        return QualityGateProfile(
            1, raw["task"], {key: float(value) for key, value in minimums.items()}
        )
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        raise EvaluationDataError(f"Quality gate profile {path} is not valid.") from None


def check_evaluation_report(
    report: dict[str, Any], profile: QualityGateProfile
) -> QualityGateResult:
    if report.get("task") != profile.task:
        raise ValueError(f"Report task does not match profile task {profile.task}.")
    metrics = report.get("metrics")
    if not isinstance(metrics, dict):
        raise EvaluationDataError("Evaluation report metrics are not valid.")
    requirements = {}
    for name, minimum in profile.minimums.items():
        value = _metric(metrics, name)
        met = value is not None and value >= minimum
        requirements[name] = {"minimum": minimum, "actual": value, "passed": met}
    return QualityGateResult(all(item["passed"] for item in requirements.values()), requirements)


def format_quality_gate_result(result: QualityGateResult) -> str:
    lines = ["PASS" if result.passed else "FAIL"]
    for name, item in result.requirements.items():
        actual = "undefined" if item["actual"] is None else f"{item['actual']:g}"
        status = "pass" if item["passed"] else "missed"
        lines.append(f"{name}: {actual} (minimum {item['minimum']:g}, {status})")
    return "\n".join(lines) + "\n"


def _metric(metrics: dict[str, Any], path: str) -> float | None:
    value: Any = metrics
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None
