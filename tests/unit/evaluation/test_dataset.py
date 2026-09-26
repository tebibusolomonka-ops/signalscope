import dataclasses

import pytest

from signalscope.core.errors import SignalScopeError
from signalscope.evaluation.dataset import (
    EvaluationDataError,
    EvaluationDocument,
    EvaluationQuery,
    RetrievalDataset,
)

WIND = EvaluationDocument("energy-1", "Offshore wind farms grew.", "Offshore wind", "en")
RAIN = EvaluationDocument("weather-1", "Heavy rain flooded the city.")
QUERY = EvaluationQuery("q1", "offshore renewable energy", frozenset({"energy-1"}))


def test_valid_dataset() -> None:
    dataset = RetrievalDataset("media-smoke", (WIND, RAIN), (QUERY,))

    assert dataset.name == "media-smoke"
    assert [document.key for document in dataset.documents] == ["energy-1", "weather-1"]
    assert dataset.queries[0].relevant_documents == frozenset({"energy-1"})
    assert (RAIN.title, RAIN.language) == (None, None)


def test_lists_become_tuples() -> None:
    dataset = RetrievalDataset("media-smoke", [WIND], [QUERY])  # type: ignore[arg-type]
    query = EvaluationQuery("q2", "wind", {"energy-1"})  # type: ignore[arg-type]

    assert isinstance(dataset.documents, tuple)
    assert isinstance(dataset.queries, tuple)
    assert isinstance(query.relevant_documents, frozenset)


def test_values_cannot_be_changed() -> None:
    dataset = RetrievalDataset("media-smoke", (WIND,), (QUERY,))

    with pytest.raises(dataclasses.FrozenInstanceError):
        dataset.name = "other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        WIND.text = "other"  # type: ignore[misc]


def test_duplicate_document_keys() -> None:
    with pytest.raises(EvaluationDataError, match="document key 'energy-1' twice"):
        RetrievalDataset("media-smoke", (WIND, WIND), (QUERY,))


def test_duplicate_query_keys() -> None:
    with pytest.raises(EvaluationDataError, match="query key 'q1' twice"):
        RetrievalDataset("media-smoke", (WIND,), (QUERY, QUERY))


def test_unknown_relevant_document() -> None:
    query = EvaluationQuery("q2", "rain", frozenset({"weather-9", "energy-1"}))

    with pytest.raises(EvaluationDataError, match="'q2' .* unknown documents: weather-9"):
        RetrievalDataset("media-smoke", (WIND,), (query,))


def test_query_needs_a_relevant_document() -> None:
    with pytest.raises(EvaluationDataError, match="at least one relevant document"):
        EvaluationQuery("q1", "wind", frozenset())


@pytest.mark.parametrize(
    "make",
    [
        lambda: EvaluationDocument(" ", "text"),
        lambda: EvaluationDocument("key", "  "),
        lambda: EvaluationDocument("key", "text", title=""),
        lambda: EvaluationDocument("key", "text", language=" "),
        lambda: EvaluationQuery("", "wind", frozenset({"energy-1"})),
        lambda: EvaluationQuery("q1", "\n", frozenset({"energy-1"})),
        lambda: RetrievalDataset(" ", (WIND,), (QUERY,)),
    ],
    ids=[
        "document key",
        "document text",
        "title",
        "language",
        "query key",
        "query text",
        "dataset name",
    ],
)
def test_blank_values_are_rejected(make: object) -> None:
    with pytest.raises(EvaluationDataError, match="must not be empty"):
        make()  # type: ignore[operator]


def test_dataset_needs_documents_and_queries() -> None:
    with pytest.raises(EvaluationDataError, match="no documents"):
        RetrievalDataset("media-smoke", (), (QUERY,))
    with pytest.raises(EvaluationDataError, match="no queries"):
        RetrievalDataset("media-smoke", (WIND,), ())


def test_error_type() -> None:
    assert issubclass(EvaluationDataError, SignalScopeError)
    assert issubclass(EvaluationDataError, ValueError)
