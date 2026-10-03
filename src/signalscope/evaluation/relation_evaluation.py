from dataclasses import asdict, dataclass
from typing import Any

from signalscope.evaluation.relation_dataset import (
    RelationDataset,
    RelationTriple,
    normalize_relation_part,
)


@dataclass(frozen=True, slots=True)
class RelationPrediction:
    example_key: str
    subject: str
    relation_type: str
    object: str
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class RelationTypeMetrics:
    precision: float | None
    recall: float | None
    f1: float | None
    support: int
    predicted_count: int
    true_positive_count: int


@dataclass(frozen=True, slots=True)
class RelationEvaluationReport:
    task: str
    model: str
    provider: str
    dataset: dict[str, str]
    records_evaluated: int
    reference_triple_count: int
    predicted_triple_count: int
    true_positive_count: int
    false_positive_count: int
    false_negative_count: int
    micro_precision: float | None
    micro_recall: float | None
    micro_f1: float | None
    per_type: dict[str, RelationTypeMetrics]
    false_positives: tuple[dict[str, str], ...]
    false_negatives: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_relation_types(
    dataset: RelationDataset,
    predictions: list[RelationPrediction],
    *,
    error_example_limit: int = 20,
    model: str = "unspecified",
    provider: str = "unspecified",
) -> RelationEvaluationReport:
    references = [
        _item(example.key, triple) for example in dataset.examples for triple in example.relations
    ]
    predicted = [_prediction_item(item) for item in predictions]
    remaining = list(references)
    true_positives = []
    false_positives = []
    for item in predicted:
        if item in remaining:
            remaining.remove(item)
            true_positives.append(item)
        else:
            false_positives.append(item)
    false_negatives = remaining
    relation_types = sorted({item[2] for item in references + predicted})
    per_type = {}
    for relation_type in relation_types:
        support = sum(item[2] == relation_type for item in references)
        predicted_count = sum(item[2] == relation_type for item in predicted)
        matched = sum(item[2] == relation_type for item in true_positives)
        precision = _ratio(matched, predicted_count)
        recall = _ratio(matched, support)
        per_type[relation_type] = RelationTypeMetrics(
            precision, recall, _f1(precision, recall), support, predicted_count, matched
        )
    precision = _ratio(len(true_positives), len(predicted))
    recall = _ratio(len(true_positives), len(references))
    return RelationEvaluationReport(
        task="relation_evaluation",
        model=model,
        provider=provider,
        dataset={
            "name": dataset.name,
            "version": dataset.version,
            "fingerprint": dataset.fingerprint(),
        },
        records_evaluated=len(dataset.examples),
        reference_triple_count=len(references),
        predicted_triple_count=len(predicted),
        true_positive_count=len(true_positives),
        false_positive_count=len(false_positives),
        false_negative_count=len(false_negatives),
        micro_precision=precision,
        micro_recall=recall,
        micro_f1=_f1(precision, recall),
        per_type=per_type,
        false_positives=tuple(
            _compact(item) for item in sorted(false_positives)[:error_example_limit]
        ),
        false_negatives=tuple(
            _compact(item) for item in sorted(false_negatives)[:error_example_limit]
        ),
    )


def _item(example_key: str, triple: RelationTriple) -> tuple[str, str, str, str]:
    return (
        example_key,
        normalize_relation_part(triple.subject),
        normalize_relation_part(triple.relation_type),
        normalize_relation_part(triple.object),
    )


def _prediction_item(item: RelationPrediction) -> tuple[str, str, str, str]:
    return (
        item.example_key,
        normalize_relation_part(item.subject),
        normalize_relation_part(item.relation_type),
        normalize_relation_part(item.object),
    )


def _compact(item: tuple[str, str, str, str]) -> dict[str, str]:
    return {"example_key": item[0], "subject": item[1], "relation_type": item[2], "object": item[3]}


def _ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)
