"""User-supplied minimum scores for extraction evaluation.

SignalScope has no built-in targets. A gates file names, per mode, the
metrics that must reach a minimum:

    {
      "event": {"precision": 0.7, "recall": 0.6, "f1": 0.65},
      "claim": {"f1": 0.7},
      "relation": {"precision": 0.8}
    }

Modes are event, claim and relation. Metrics are precision, recall and f1.
A gate is missed when its value is lower, undefined, or its mode did not run.
"""

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalscope.evaluation.extraction.scoring import ExtractionScore
from signalscope.evaluation.gates import MAX_GATES_BYTES, QualityGateError

EXTRACTION_GATE_MODES = ("event", "claim", "relation")
EXTRACTION_GATE_METRICS = ("precision", "recall", "f1")


@dataclass(frozen=True, slots=True)
class ExtractionGate:
    mode: str
    metric: str
    minimum: float

    @property
    def label(self) -> str:
        return f"{self.mode.capitalize()} {self.metric}"


@dataclass(frozen=True, slots=True)
class ExtractionGateResult:
    gate: ExtractionGate
    # False when the mode did not run.
    evaluated: bool
    # None when the metric is undefined, such as precision with no predictions.
    value: float | None

    @property
    def passed(self) -> bool:
        return self.value is not None and self.value >= self.gate.minimum


def load_extraction_gates(path: Path) -> list[ExtractionGate]:
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
    return parse_extraction_gates(raw)


def parse_extraction_gates(raw: Any) -> list[ExtractionGate]:
    if not isinstance(raw, dict) or not raw:
        raise QualityGateError("Quality gates must be a JSON object with at least one mode.")
    gates = []
    for mode, metrics in raw.items():
        if mode not in EXTRACTION_GATE_MODES:
            raise QualityGateError(
                f"Quality gates name unknown mode {mode!r}. "
                f"Modes are: {', '.join(EXTRACTION_GATE_MODES)}."
            )
        if not isinstance(metrics, dict) or not metrics:
            raise QualityGateError(f"Quality gates for {mode} must be an object of metrics.")
        for metric, minimum in metrics.items():
            if metric not in EXTRACTION_GATE_METRICS:
                raise QualityGateError(
                    f"Quality gate {mode}/{metric} is not a known metric. "
                    f"Use {', '.join(EXTRACTION_GATE_METRICS)}."
                )
            if (
                isinstance(minimum, bool)
                or not isinstance(minimum, int | float)
                or not math.isfinite(minimum)
                or not 0 <= minimum <= 1
            ):
                raise QualityGateError(
                    f"Quality gate {mode}/{metric} needs a minimum between 0 and 1."
                )
            gates.append(ExtractionGate(mode, metric, float(minimum)))
    return gates


def check_extraction_gates(
    gates: Sequence[ExtractionGate], scores: Sequence[ExtractionScore]
) -> list[ExtractionGateResult]:
    by_mode = {score.kind: score for score in scores}
    results = []
    for gate in gates:
        score = by_mode.get(gate.mode)
        value = None if score is None else getattr(score, gate.metric)
        results.append(ExtractionGateResult(gate, score is not None, value))
    return results


def format_extraction_gate_results(results: Sequence[ExtractionGateResult]) -> str:
    """Only says whether each supplied minimum was reached."""
    lines = ["", "Quality gates"]
    for result in results:
        if not result.evaluated:
            value = "not run"
        elif result.value is None:
            value = "undefined"
        else:
            value = f"{result.value:.3f}"
        outcome = "passed" if result.passed else "missed"
        lines.append(f"{result.gate.label}: {value}, minimum {result.gate.minimum:.3f}, {outcome}")
    missed = sum(not result.passed for result in results)
    lines.append(f"Gates missed: {missed} of {len(results)}")
    return "\n".join(lines) + "\n"
