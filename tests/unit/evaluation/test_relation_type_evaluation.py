from signalscope.evaluation.relation_dataset import (
    RelationDataset,
    RelationExample,
    RelationTriple,
)
from signalscope.evaluation.relation_evaluation import (
    RelationPrediction,
    evaluate_relation_types,
)


def _dataset(*relations: RelationTriple) -> RelationDataset:
    return RelationDataset(
        1, "relations", "1", (RelationExample("one", "text", None, (), relations),)
    )


def _prediction(subject="Ana", relation_type="works_for", object="Acme"):
    return RelationPrediction("one", subject, relation_type, object)


def test_perfect_match_uses_explicit_normalization() -> None:
    report = evaluate_relation_types(
        _dataset(RelationTriple("Ana", "works_for", "Acme")),
        [_prediction(" ana ", "WORKS_FOR", "ACME")],
    )
    assert (report.micro_precision, report.micro_recall, report.micro_f1) == (1.0, 1.0, 1.0)
    assert report.per_type["works_for"].support == 1


def test_false_positive_and_zero_support_type() -> None:
    report = evaluate_relation_types(
        _dataset(RelationTriple("Ana", "works_for", "Acme")),
        [_prediction(), _prediction("Acme", "located_in", "Porto")],
    )
    assert report.micro_precision == 0.5
    assert report.false_positive_count == 1
    assert report.per_type["located_in"].support == 0
    assert report.per_type["located_in"].recall is None


def test_false_negative_and_multiple_types_are_sorted() -> None:
    report = evaluate_relation_types(
        _dataset(
            RelationTriple("Ana", "works_for", "Acme"),
            RelationTriple("Acme", "located_in", "Porto"),
        ),
        [_prediction()],
    )
    assert report.micro_recall == 0.5
    assert report.false_negative_count == 1
    assert list(report.per_type) == ["located_in", "works_for"]


def test_duplicate_prediction_is_false_positive() -> None:
    report = evaluate_relation_types(
        _dataset(RelationTriple("Ana", "works_for", "Acme")), [_prediction(), _prediction()]
    )
    assert (report.true_positive_count, report.false_positive_count) == (1, 1)


def test_zero_predictions_is_safe() -> None:
    report = evaluate_relation_types(_dataset(RelationTriple("Ana", "works_for", "Acme")), [])
    assert report.micro_precision is None
    assert report.micro_recall == 0.0
    assert report.micro_f1 is None


def test_zero_references_is_safe_and_errors_are_bounded() -> None:
    predictions = [_prediction(object=str(index)) for index in range(5)]
    report = evaluate_relation_types(_dataset(), predictions, error_example_limit=2)
    assert report.micro_recall is None
    assert report.micro_precision == 0.0
    assert report.micro_f1 is None
    assert len(report.false_positives) == 2


def test_error_examples_have_deterministic_order() -> None:
    report = evaluate_relation_types(
        _dataset(), [_prediction(object="Zulu"), _prediction(object="Alpha")]
    )
    assert [item["object"] for item in report.false_positives] == ["alpha", "zulu"]
