from signalscope.evaluation.relation_confidence import analyze_relation_confidence
from signalscope.evaluation.relation_dataset import (
    RelationDataset,
    RelationExample,
    RelationTriple,
)
from signalscope.evaluation.relation_evaluation import RelationPrediction

DATASET = RelationDataset(
    1,
    "relations",
    "1",
    (
        RelationExample(
            "one",
            "text",
            None,
            (),
            (RelationTriple("Ana", "works_for", "Acme"),),
        ),
    ),
)


def prediction(obj: str, confidence: float | None) -> RelationPrediction:
    return RelationPrediction("one", "Ana", "works_for", obj, confidence)


def test_reports_confidence_unavailable() -> None:
    result = analyze_relation_confidence(DATASET, [prediction("Acme", None)])
    assert result.confidence_available is False
    assert result.predictions_without_confidence == 1
    assert all(bucket.prediction_count == 0 for bucket in result.buckets)


def test_bucket_boundaries_and_empty_bucket() -> None:
    result = analyze_relation_confidence(
        DATASET,
        [prediction("Acme", 0.5), prediction("Wrong", 1.0)],
        boundaries=(0.0, 0.5, 0.8, 1.0),
    )
    assert result.confidence_available is True
    assert result.buckets[0].prediction_count == 0
    assert result.buckets[1].precision == 1.0
    assert result.buckets[2].precision == 0.0


def test_all_correct_and_all_wrong_buckets() -> None:
    result = analyze_relation_confidence(
        DATASET, [prediction("Acme", 0.2), prediction("Wrong", 0.7)]
    )
    assert result.buckets[0].correct_prediction_count == 1
    assert result.buckets[0].incorrect_prediction_count == 0
    assert result.buckets[1].correct_prediction_count == 0
    assert result.buckets[1].incorrect_prediction_count == 1
