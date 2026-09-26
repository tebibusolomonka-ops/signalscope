import json
from pathlib import Path
from typing import Any

import pytest

from signalscope.evaluation import loader
from signalscope.evaluation.dataset import EvaluationDataError
from signalscope.evaluation.loader import load_dataset, parse_dataset

VALID: dict[str, Any] = {
    "name": "media-smoke",
    "documents": [
        {
            "key": "energy-1",
            "title": "Offshore wind expansion",
            "text": "Offshore wind farms doubled their output.",
            "language": "en",
        },
        {"key": "weather-1", "text": "Heavy rain flooded the city."},
    ],
    "queries": [
        {"key": "q1", "text": "offshore renewable energy", "relevant_documents": ["energy-1"]}
    ],
}


def write(path: Path, content: Any) -> Path:
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def changed(**fields: Any) -> dict[str, Any]:
    return VALID | fields


def test_load_valid_file(tmp_path: Path) -> None:
    dataset = load_dataset(write(tmp_path / "smoke.json", VALID))

    assert dataset.name == "media-smoke"
    wind, rain = dataset.documents
    assert (wind.key, wind.title, wind.language) == ("energy-1", "Offshore wind expansion", "en")
    assert (rain.title, rain.language) == (None, None)
    assert dataset.queries[0].relevant_documents == frozenset({"energy-1"})


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(EvaluationDataError, match="Cannot read dataset file"):
        load_dataset(tmp_path / "missing.json")


def test_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"name": "x",', encoding="utf-8")

    with pytest.raises(EvaluationDataError, match="not valid JSON: .* at line 1"):
        load_dataset(path)


def test_not_utf8() -> None:
    with pytest.raises(EvaluationDataError, match="not UTF-8"):
        parse_dataset(b"\xff\xfe{}", "bytes")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ([], "must be a JSON object"),
        ({"name": "x", "documents": []}, "missing fields: queries"),
        (changed(extra=1), "unknown fields: extra"),
        (changed(name=3), "name must be text"),
        (changed(documents={}), "documents must be a list"),
        (changed(documents=["text"]), r"documents\[0\] must be a JSON object"),
        (changed(documents=[{"key": "a"}]), r"documents\[0\] is missing fields: text"),
        (
            changed(documents=[{"key": "a", "text": "t", "author": "x"}]),
            "unknown fields: author",
        ),
        (changed(documents=[{"key": "a", "text": 5}]), "text must be text"),
        (changed(queries=[{"key": "q1", "text": "t"}]), "missing fields: relevant_documents"),
        (
            changed(queries=[{"key": "q1", "text": "t", "relevant_documents": "energy-1"}]),
            "must be a list of keys",
        ),
    ],
    ids=[
        "not an object",
        "missing queries",
        "unknown dataset field",
        "name not text",
        "documents not a list",
        "document not an object",
        "document without text",
        "unknown document field",
        "text not text",
        "query without relevance",
        "relevance not a list",
    ],
)
def test_wrong_structure(tmp_path: Path, content: Any, message: str) -> None:
    with pytest.raises(EvaluationDataError, match=message):
        load_dataset(write(tmp_path / "bad.json", content))


def test_duplicate_keys(tmp_path: Path) -> None:
    documents = [VALID["documents"][0], VALID["documents"][0]]

    with pytest.raises(EvaluationDataError, match="document key 'energy-1' twice"):
        load_dataset(write(tmp_path / "bad.json", changed(documents=documents)))


def test_unknown_relevant_document(tmp_path: Path) -> None:
    queries = [{"key": "q1", "text": "wind", "relevant_documents": ["energy-9"]}]

    with pytest.raises(EvaluationDataError, match="unknown documents: energy-9"):
        load_dataset(write(tmp_path / "bad.json", changed(queries=queries)))


def test_empty_dataset(tmp_path: Path) -> None:
    with pytest.raises(EvaluationDataError, match="no documents"):
        load_dataset(write(tmp_path / "empty.json", changed(documents=[], queries=[])))


def test_error_names_the_dataset_without_its_content(tmp_path: Path) -> None:
    long_text = "secret words " * 1000
    documents = [{"key": "a", "text": long_text, "author": "x"}]

    with pytest.raises(EvaluationDataError) as error:
        load_dataset(write(tmp_path / "bad.json", changed(documents=documents)))

    assert "'media-smoke' documents[0]" in str(error.value)
    assert "secret words" not in str(error.value)


def test_file_that_is_too_large(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader, "MAX_DATASET_BYTES", 100)
    path = write(tmp_path / "large.json", VALID)

    with pytest.raises(EvaluationDataError, match="larger than"):
        load_dataset(path)


def test_too_many_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader, "MAX_DOCUMENTS", 1)

    with pytest.raises(EvaluationDataError, match="more than 1 documents"):
        load_dataset(write(tmp_path / "many.json", VALID))


def test_too_many_queries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader, "MAX_QUERIES", 1)
    queries = VALID["queries"] * 2

    with pytest.raises(EvaluationDataError, match="more than 1 queries"):
        load_dataset(write(tmp_path / "many.json", changed(queries=queries)))
