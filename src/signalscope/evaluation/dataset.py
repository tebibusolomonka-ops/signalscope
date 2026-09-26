"""Retrieval test sets: documents, queries, and which documents each query should find."""

from collections.abc import Iterable
from dataclasses import dataclass

from signalscope.core.errors import SignalScopeError


class EvaluationDataError(SignalScopeError, ValueError):
    default_message = "Evaluation data is not valid."


@dataclass(frozen=True, slots=True)
class EvaluationDocument:
    # A name that is unique within the dataset, such as "energy-1".
    key: str
    text: str
    title: str | None = None
    language: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.key, "Document key")
        _require_text(self.text, f"Document {self.key!r} text")
        if self.title is not None:
            _require_text(self.title, f"Document {self.key!r} title")
        if self.language is not None:
            _require_text(self.language, f"Document {self.key!r} language")


@dataclass(frozen=True, slots=True)
class EvaluationQuery:
    key: str
    text: str
    # Keys of the documents a good search returns for this query. Every other
    # document counts as not relevant.
    relevant_documents: frozenset[str]

    def __post_init__(self) -> None:
        _require_text(self.key, "Query key")
        _require_text(self.text, f"Query {self.key!r} text")
        object.__setattr__(self, "relevant_documents", frozenset(self.relevant_documents))
        if not self.relevant_documents:
            raise EvaluationDataError(f"Query {self.key!r} needs at least one relevant document.")


@dataclass(frozen=True, slots=True)
class RetrievalDataset:
    name: str
    documents: tuple[EvaluationDocument, ...]
    queries: tuple[EvaluationQuery, ...]

    def __post_init__(self) -> None:
        _require_text(self.name, "Dataset name")
        object.__setattr__(self, "documents", tuple(self.documents))
        object.__setattr__(self, "queries", tuple(self.queries))
        if not self.documents:
            raise EvaluationDataError(f"Dataset {self.name!r} has no documents.")
        if not self.queries:
            raise EvaluationDataError(f"Dataset {self.name!r} has no queries.")
        _require_unique((document.key for document in self.documents), "document", self.name)
        _require_unique((query.key for query in self.queries), "query", self.name)
        known = {document.key for document in self.documents}
        for query in self.queries:
            unknown = sorted(query.relevant_documents - known)
            if unknown:
                raise EvaluationDataError(
                    f"Query {query.key!r} in dataset {self.name!r} names unknown "
                    f"documents: {', '.join(unknown)}"
                )


def _require_text(value: str, what: str) -> None:
    if not value.strip():
        raise EvaluationDataError(f"{what} must not be empty.")


def _require_unique(keys: Iterable[str], kind: str, dataset: str) -> None:
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            raise EvaluationDataError(f"Dataset {dataset!r} has the {kind} key {key!r} twice.")
        seen.add(key)
