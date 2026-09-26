"""User-supplied minimum scores for retrieval evaluation.

SignalScope has no built-in targets. A gates file names, per mode, the
metrics that must reach a minimum:

    {
      "hybrid": {"recall@10": 0.8, "mrr@10": 0.5},
      "reranked": {"ndcg@10": 0.6}
    }

Metrics are recall, mrr and ndcg, each with an @k cut-off.
"""

import json
import math
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalscope.domain.search.repository import PUBLIC_SEARCH_LIMIT
from signalscope.evaluation.dataset import EvaluationDataError
from signalscope.evaluation.retrieval import RetrievalReport

MAX_GATES_BYTES = 64 * 1024
METRIC_NAMES = {"recall": "Recall", "mrr": "MRR", "ndcg": "nDCG"}
METRIC_PATTERN = re.compile(r"(recall|mrr|ndcg)@(\d+)")


class QualityGateError(EvaluationDataError):
    default_message = "Quality gates are not valid."


@dataclass(frozen=True, slots=True)
class QualityGate:
    mode: str
    metric: str
    k: int
    minimum: float

    @property
    def label(self) -> str:
        return f"{self.mode.capitalize()} {METRIC_NAMES[self.metric]}@{self.k}"


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: QualityGate
    # None when the mode did not run.
    value: float | None

    @property
    def passed(self) -> bool:
        return self.value is not None and self.value >= self.gate.minimum


def load_quality_gates(path: Path, modes: Collection[str]) -> list[QualityGate]:
    """Read a gates file. modes are the mode names a gate may use."""
    try:
        if path.stat().st_size > MAX_GATES_BYTES:
            raise QualityGateError(f"Quality gates file {path} is larger than 64 KB.")
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise QualityGateError(f"Cannot read quality gates file {path}: {error.strerror}") from None
    except UnicodeDecodeError:
        raise QualityGateError(f"Quality gates file {path} is not UTF-8 text.") from None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise QualityGateError(
            f"Quality gates file {path} is not valid JSON: {error.msg} at line {error.lineno}."
        ) from None
    return parse_quality_gates(raw, modes)


def parse_quality_gates(raw: Any, modes: Collection[str]) -> list[QualityGate]:
    if not isinstance(raw, dict) or not raw:
        raise QualityGateError("Quality gates must be a JSON object with at least one mode.")
    gates = []
    for mode, metrics in raw.items():
        if mode not in modes:
            raise QualityGateError(
                f"Quality gates name unknown mode {mode!r}. Modes are: {', '.join(modes)}."
            )
        if not isinstance(metrics, dict) or not metrics:
            raise QualityGateError(f"Quality gates for {mode} must be an object of metrics.")
        for name, minimum in metrics.items():
            gates.append(_gate(mode, name, minimum))
    return gates


def check_gates(
    gates: Sequence[QualityGate], reports: Sequence[RetrievalReport]
) -> list[GateResult]:
    by_mode = {report.mode: report for report in reports}
    results = []
    for gate in gates:
        report = by_mode.get(gate.mode)
        value = None
        if report is not None:
            value = getattr(report.metrics, gate.metric)[gate.k]
        results.append(GateResult(gate, value))
    return results


def format_gate_results(results: Sequence[GateResult]) -> str:
    """Only says whether each supplied minimum was reached."""
    lines = ["", "Quality gates"]
    for result in results:
        value = "not run" if result.value is None else f"{result.value:.3f}"
        outcome = "passed" if result.passed else "missed"
        lines.append(f"{result.gate.label}: {value}, minimum {result.gate.minimum:.3f}, {outcome}")
    missed = sum(not result.passed for result in results)
    lines.append(f"Gates missed: {missed} of {len(results)}")
    return "\n".join(lines) + "\n"


def _gate(mode: str, name: Any, minimum: Any) -> QualityGate:
    match = METRIC_PATTERN.fullmatch(name) if isinstance(name, str) else None
    if match is None:
        raise QualityGateError(
            f"Quality gate {mode}/{name} is not a known metric. Use recall@k, mrr@k or ndcg@k."
        )
    metric, k = match[1], int(match[2])
    if not 1 <= k <= PUBLIC_SEARCH_LIMIT:
        raise QualityGateError(
            f"Quality gate {mode}/{name} needs k between 1 and {PUBLIC_SEARCH_LIMIT}."
        )
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, int | float)
        or not math.isfinite(minimum)
        or not 0 <= minimum <= 1
    ):
        raise QualityGateError(f"Quality gate {mode}/{name} needs a minimum between 0 and 1.")
    return QualityGate(mode, metric, k, float(minimum))
