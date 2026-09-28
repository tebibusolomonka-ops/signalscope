"""Plain text and JSON reports of extraction scores.

They give numbers only. There are no built-in targets, so nothing is called
good or bad.
"""

from collections.abc import Sequence
from typing import Any

from signalscope.evaluation.extraction.dataset import ExtractionDataset
from signalscope.evaluation.extraction.scoring import ExtractionScore

HEADINGS = {"event": "Events", "claim": "Claims", "relation": "Relations"}


def format_extraction_scores(dataset: ExtractionDataset, scores: Sequence[ExtractionScore]) -> str:
    lines = [f"Dataset: {dataset.name}", f"Documents: {len(dataset.documents)}"]
    for score in scores:
        lines += [
            "",
            HEADINGS[score.kind],
            f"Model: {score.provider}/{score.model}",
            f"Gold: {score.gold_count}",
            f"Predicted: {score.predicted_count}",
            f"Matched: {score.matched_count}",
            f"Precision: {_number(score.precision)}",
            f"Recall: {_number(score.recall)}",
            f"F1: {_number(score.f1)}",
        ]
    return "\n".join(lines) + "\n"


def extraction_report_data(
    dataset: ExtractionDataset, scores: Sequence[ExtractionScore]
) -> dict[str, Any]:
    """The scores as JSON values, with what each document missed or added."""
    return {
        "dataset": dataset.name,
        "documents": len(dataset.documents),
        "results": {
            score.kind: {
                "provider": score.provider,
                "model": score.model,
                "gold_count": score.gold_count,
                "predicted_count": score.predicted_count,
                "matched_count": score.matched_count,
                "precision": score.precision,
                "recall": score.recall,
                "f1": score.f1,
                "documents": [
                    {
                        "key": document.document_key,
                        "gold_count": document.gold_count,
                        "predicted_count": document.predicted_count,
                        "matched_count": document.matched_count,
                        "missed": list(document.missed),
                        "extra": list(document.extra),
                    }
                    for document in score.documents
                ],
            }
            for score in scores
        },
    }


def _number(value: float | None) -> str:
    # None means the value is undefined, such as precision with no predictions.
    return "n/a" if value is None else f"{value:.3f}"
