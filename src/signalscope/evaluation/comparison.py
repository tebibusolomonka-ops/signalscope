import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalscope.evaluation.dataset import EvaluationDataError


@dataclass(frozen=True, slots=True)
class ReportComparison:
    task: str
    dataset_fingerprint: str
    reports: tuple[str, ...]
    metrics: dict[str, tuple[float, ...]]
    timings: dict[str, tuple[float, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "dataset_fingerprint": self.dataset_fingerprint,
            "reports": list(self.reports),
            "metrics": _differences(self.metrics),
            "timings": _differences(self.timings),
        }


def compare_evaluation_reports(paths: list[Path]) -> ReportComparison:
    if len(paths) < 2:
        raise ValueError("At least two evaluation reports are required.")
    reports = [_load(path) for path in paths]
    task = reports[0]["task"]
    fingerprint = reports[0]["dataset"]["fingerprint"]
    if any(report["task"] != task for report in reports[1:]):
        raise ValueError("Evaluation reports have different tasks.")
    if any(report["dataset"]["fingerprint"] != fingerprint for report in reports[1:]):
        raise ValueError("Evaluation reports use different datasets.")
    metrics = _common_numbers([report["metrics"] for report in reports])
    if not metrics:
        raise ValueError("Evaluation reports have no compatible metrics.")
    timings = _common_numbers([report["timings"] for report in reports])
    return ReportComparison(
        task=task,
        dataset_fingerprint=fingerprint,
        reports=tuple(path.name for path in paths),
        metrics=metrics,
        timings=timings,
    )


def format_comparison(comparison: ReportComparison) -> str:
    lines = [f"Task: {comparison.task}", f"Dataset: {comparison.dataset_fingerprint}"]
    for section, values in (("Metrics", comparison.metrics), ("Timings", comparison.timings)):
        if not values:
            continue
        lines.extend(["", section])
        for name, series in values.items():
            lines.append(f"{name}:")
            for index, value in enumerate(series):
                delta = value - series[0]
                suffix = "" if index == 0 else f" (delta {delta:+g})"
                lines.append(f"  {comparison.reports[index]} {value:g}{suffix}")
    return "\n".join(lines) + "\n"


def _load(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or report.get("report_version") != 1:
            raise TypeError
        if not isinstance(report["task"], str):
            raise TypeError
        if not isinstance(report["dataset"]["fingerprint"], str):
            raise TypeError
        if not isinstance(report["metrics"], dict) or not isinstance(report["timings"], dict):
            raise TypeError
        return report
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        raise EvaluationDataError(f"Evaluation report {path} is not valid.") from None


def _common_numbers(values: list[dict[str, Any]]) -> dict[str, tuple[float, ...]]:
    flattened = [_flatten(value) for value in values]
    common = set(flattened[0]).intersection(*(set(value) for value in flattened[1:]))
    return {
        key: tuple(value[key] for value in flattened)
        for key in sorted(common)
        if all(isinstance(value[key], (int, float)) for value in flattened)
    }


def _flatten(value: dict[str, Any], prefix: str = "") -> dict[str, float]:
    result = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            result.update(_flatten(item, name))
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            result[name] = float(item)
    return result


def _differences(values: dict[str, tuple[float, ...]]) -> dict[str, Any]:
    return {
        name: {"values": list(series), "deltas": [value - series[0] for value in series]}
        for name, series in values.items()
    }
