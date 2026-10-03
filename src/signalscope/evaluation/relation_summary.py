from typing import Any

from signalscope.evaluation.dataset import EvaluationDataError


def relation_evaluation_summary(
    report: dict[str, Any],
    *,
    confidence: dict[str, Any] | None = None,
    readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if report.get("task") != "relation_evaluation":
        raise EvaluationDataError("Report task is not relation_evaluation.")
    required = (
        "dataset",
        "model",
        "provider",
        "records_evaluated",
        "reference_triple_count",
        "predicted_triple_count",
        "micro_precision",
        "micro_recall",
        "micro_f1",
        "per_type",
    )
    if any(name not in report for name in required):
        raise EvaluationDataError("Relation evaluation report is missing required fields.")
    confidence_summary: dict[str, Any]
    if confidence is None or not confidence.get("confidence_available"):
        confidence_summary = {
            "available": False,
            "observation": "Confidence was not provided by the evaluated output.",
        }
    else:
        confidence_summary = {"available": True, "buckets": confidence.get("buckets", [])}
    requirements: dict[str, list[dict[str, Any]]] = {"met": [], "missed": []}
    if readiness is not None:
        for item in readiness.get("requirements", []):
            target = "met" if item.get("met") else "missed"
            requirements[target].append(item)
    limitations = [
        f"Dataset contains {report['records_evaluated']} evaluated records.",
        "Triples are scored with exact deterministic matching after normalization.",
    ]
    if not confidence_summary["available"]:
        limitations.append("Confidence is unavailable for this evaluated output.")
    low_support = sorted(
        name for name, metrics in report["per_type"].items() if metrics.get("support", 0) < 2
    )
    if low_support:
        limitations.append("Limited support: " + ", ".join(low_support) + ".")
    return {
        "task": "relation_evaluation_summary",
        "dataset": report["dataset"],
        "model": report["model"],
        "provider": report["provider"],
        "records_evaluated": report["records_evaluated"],
        "reference_triple_count": report["reference_triple_count"],
        "predicted_triple_count": report["predicted_triple_count"],
        "micro": {
            "precision": report["micro_precision"],
            "recall": report["micro_recall"],
            "f1": report["micro_f1"],
        },
        "per_type": report["per_type"],
        "confidence": confidence_summary,
        "requirements": requirements,
        "limitations": limitations,
    }


def format_relation_summary(summary: dict[str, Any]) -> str:
    dataset = summary["dataset"]
    lines = [
        f"Dataset: {dataset['name']} {dataset['version']} ({dataset['fingerprint']})",
        f"Model: {summary['model']}",
        f"Provider: {summary['provider']}",
        f"Records evaluated: {summary['records_evaluated']}",
        f"Reference relations: {summary['reference_triple_count']}",
        f"Predicted relations: {summary['predicted_triple_count']}",
        f"Micro precision: {_number(summary['micro']['precision'])}",
        f"Micro recall: {_number(summary['micro']['recall'])}",
        f"Micro F1: {_number(summary['micro']['f1'])}",
        "",
        "Per relation type",
    ]
    for name in sorted(summary["per_type"]):
        item = summary["per_type"][name]
        lines.append(
            f"{name}: support {item['support']}, precision {_number(item['precision'])}, "
            f"recall {_number(item['recall'])}, F1 {_number(item['f1'])}"
        )
    lines.extend(["", "Confidence", summary["confidence"].get("observation", "Buckets included.")])
    lines.extend(["", "Requirements"])
    lines.append(f"Met: {len(summary['requirements']['met'])}")
    lines.append(f"Missed: {len(summary['requirements']['missed'])}")
    lines.extend(["", "Limitations", *summary["limitations"]])
    return "\n".join(lines) + "\n"


def _number(value: float | None) -> str:
    return "undefined" if value is None else f"{value:.3f}"
