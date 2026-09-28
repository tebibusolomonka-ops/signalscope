"""Extraction test sets: documents and the events and claims they contain."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from signalscope.evaluation.dataset import EvaluationDataError


@dataclass(frozen=True, slots=True)
class ExtractionDocument:
    # A name that is unique within the dataset, such as "flood-1".
    key: str
    text: str
    language: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.key, "Document key")
        _require_text(self.text, f"Document {self.key!r} text")
        if self.language is not None:
            _require_text(self.language, f"Document {self.key!r} language")


@dataclass(frozen=True, slots=True)
class GoldEvent:
    """An event a good model finds in the document."""

    document_key: str
    event_type: str
    title: str
    # When known, the event must be found on the same UTC day.
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text(self.event_type, f"Event type in {self.document_key!r}")
        _require_text(self.title, f"Event title in {self.document_key!r}")
        if self.occurred_at is not None and self.occurred_at.utcoffset() is None:
            raise EvaluationDataError(
                f"Event {self.title!r} in {self.document_key!r} needs a time zone."
            )


@dataclass(frozen=True, slots=True)
class GoldClaim:
    """A claim a good model finds, at exact offsets into the document text."""

    document_key: str
    claim_type: str
    surface_text: str
    start_char: int
    end_char: int

    def __post_init__(self) -> None:
        _require_text(self.claim_type, f"Claim type in {self.document_key!r}")
        _require_text(self.surface_text, f"Claim text in {self.document_key!r}")


@dataclass(frozen=True, slots=True)
class ExtractionDataset:
    name: str
    documents: tuple[ExtractionDocument, ...]
    events: tuple[GoldEvent, ...] = ()
    claims: tuple[GoldClaim, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.name, "Dataset name")
        object.__setattr__(self, "documents", tuple(self.documents))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "claims", tuple(self.claims))
        if not self.documents:
            raise EvaluationDataError(f"Dataset {self.name!r} has no documents.")
        _require_unique((document.key for document in self.documents), self.name)
        texts = {document.key: document.text for document in self.documents}
        for event in self.events:
            self._require_document(event.document_key, texts)
        for claim in self.claims:
            text = self._require_document(claim.document_key, texts)
            start, end = claim.start_char, claim.end_char
            if not 0 <= start < end <= len(text):
                raise EvaluationDataError(
                    f"Claim in {claim.document_key!r} has offsets {start}:{end} "
                    "outside the document text."
                )
            if text[start:end] != claim.surface_text:
                raise EvaluationDataError(
                    f"Claim text in {claim.document_key!r} is not at offsets {start}:{end}."
                )

    def document(self, key: str) -> ExtractionDocument:
        [found] = [document for document in self.documents if document.key == key]
        return found

    def _require_document(self, key: str, texts: dict[str, str]) -> str:
        if key not in texts:
            raise EvaluationDataError(f"Dataset {self.name!r} has no document {key!r}.")
        return texts[key]


def _require_text(value: str, what: str) -> None:
    if not value.strip():
        raise EvaluationDataError(f"{what} must not be empty.")


def _require_unique(keys: Iterable[str], dataset: str) -> None:
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            raise EvaluationDataError(f"Dataset {dataset!r} has the document key {key!r} twice.")
        seen.add(key)
