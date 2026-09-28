"""Precision, recall and F1 for extraction, with one-to-one matching.

Each gold item can be matched by at most one prediction, and each prediction
can match at most one gold item. So a repeated prediction never raises the
score. Items are matched in order, first gold item first.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DocumentScore:
    """How one document went, with short descriptions of what did not match."""

    document_key: str
    gold_count: int
    predicted_count: int
    matched_count: int
    missed: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractionScore:
    dataset: str
    # "event", "claim" or "relation".
    kind: str
    provider: str
    model: str
    documents: tuple[DocumentScore, ...]

    @property
    def document_count(self) -> int:
        return len(self.documents)

    @property
    def gold_count(self) -> int:
        return sum(document.gold_count for document in self.documents)

    @property
    def predicted_count(self) -> int:
        return sum(document.predicted_count for document in self.documents)

    @property
    def matched_count(self) -> int:
        return sum(document.matched_count for document in self.documents)

    @property
    def precision(self) -> float | None:
        """Matched / predicted. None when nothing was predicted."""
        return _ratio(self.matched_count, self.predicted_count)

    @property
    def recall(self) -> float | None:
        """Matched / gold. None when there is no gold item."""
        return _ratio(self.matched_count, self.gold_count)

    @property
    def f1(self) -> float | None:
        precision, recall = self.precision, self.recall
        if precision is None or recall is None:
            return None
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)


def score_document[G, P](
    document_key: str,
    gold: Sequence[G],
    predicted: Sequence[P],
    matches: Callable[[G, P], bool],
    describe_gold: Callable[[G], str],
    describe_prediction: Callable[[P], str],
) -> DocumentScore:
    """Match predictions to gold items one to one and count the result."""
    unused = list(range(len(predicted)))
    missed = []
    for item in gold:
        found = next((index for index in unused if matches(item, predicted[index])), None)
        if found is None:
            missed.append(describe_gold(item))
        else:
            unused.remove(found)
    return DocumentScore(
        document_key=document_key,
        gold_count=len(gold),
        predicted_count=len(predicted),
        matched_count=len(predicted) - len(unused),
        missed=tuple(missed),
        extra=tuple(describe_prediction(predicted[index]) for index in unused),
    )


def _ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None
