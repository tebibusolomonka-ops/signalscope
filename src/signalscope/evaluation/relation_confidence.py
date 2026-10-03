import math
from dataclasses import asdict, dataclass
from typing import Any

from signalscope.evaluation.relation_dataset import RelationDataset, normalize_relation_part
from signalscope.evaluation.relation_evaluation import RelationPrediction


@dataclass(frozen=True, slots=True)
class ConfidenceBucket:
    lower: float
    upper: float
    prediction_count: int
    correct_prediction_count: int
    incorrect_prediction_count: int
    precision: float | None


@dataclass(frozen=True, slots=True)
class RelationConfidenceAnalysis:
    task: str
    confidence_available: bool
    predictions_without_confidence: int
    buckets: tuple[ConfidenceBucket, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_relation_confidence(
    dataset: RelationDataset,
    predictions: list[RelationPrediction],
    *,
    boundaries: tuple[float, ...] = (0.0, 0.5, 0.8, 1.0),
) -> RelationConfidenceAnalysis:
    _validate_boundaries(boundaries)
    references = [
        (
            example.key,
            normalize_relation_part(relation.subject),
            normalize_relation_part(relation.relation_type),
            normalize_relation_part(relation.object),
        )
        for example in dataset.examples
        for relation in example.relations
    ]
    remaining = list(references)
    scored: list[tuple[float, bool]] = []
    missing = 0
    for prediction in predictions:
        item = (
            prediction.example_key,
            normalize_relation_part(prediction.subject),
            normalize_relation_part(prediction.relation_type),
            normalize_relation_part(prediction.object),
        )
        correct = item in remaining
        if correct:
            remaining.remove(item)
        if prediction.confidence is None:
            missing += 1
            continue
        if (
            isinstance(prediction.confidence, bool)
            or not math.isfinite(prediction.confidence)
            or not 0 <= prediction.confidence <= 1
        ):
            raise ValueError("Relation confidence must be between 0 and 1.")
        scored.append((prediction.confidence, correct))
    buckets = []
    for index, (lower, upper) in enumerate(zip(boundaries, boundaries[1:], strict=False)):
        selected = [
            correct
            for confidence, correct in scored
            if lower <= confidence < upper or (index == len(boundaries) - 2 and confidence == upper)
        ]
        correct_count = sum(selected)
        buckets.append(
            ConfidenceBucket(
                lower,
                upper,
                len(selected),
                correct_count,
                len(selected) - correct_count,
                correct_count / len(selected) if selected else None,
            )
        )
    return RelationConfidenceAnalysis(
        task="relation_confidence_analysis",
        confidence_available=bool(scored),
        predictions_without_confidence=missing,
        buckets=tuple(buckets),
    )


def _validate_boundaries(boundaries: tuple[float, ...]) -> None:
    if len(boundaries) < 2 or boundaries[0] != 0 or boundaries[-1] != 1:
        raise ValueError("Confidence boundaries must start at 0 and end at 1.")
    if any(left >= right for left, right in zip(boundaries, boundaries[1:], strict=False)):
        raise ValueError("Confidence boundaries must be strictly increasing.")
