import json
from pathlib import Path

import pytest

from signalscope.evaluation.dataset import EvaluationDataError
from signalscope.evaluation.relation_dataset import load_relation_dataset


def _write(path: Path, relations=None, text="Ana works for Acme.") -> None:
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "name": "relations",
                "version": "1",
                "examples": [
                    {
                        "key": "one",
                        "text": text,
                        "mentions": ["Ana", "Acme"],
                        "relations": relations
                        or [{"subject": "Ana", "relation_type": "works_for", "object": "Acme"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_loads_valid_unicode_and_has_stable_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "relations.json"
    _write(path, text="José works for Café Acme.")
    first = load_relation_dataset(path)
    assert first.fingerprint() == load_relation_dataset(path).fingerprint()
    assert first.examples[0].text == "José works for Café Acme."


def test_fingerprint_changes_with_content(tmp_path: Path) -> None:
    path = tmp_path / "relations.json"
    _write(path)
    first = load_relation_dataset(path).fingerprint()
    _write(path, text="Ana joined Acme.")
    assert load_relation_dataset(path).fingerprint() != first


def test_rejects_invalid_and_duplicate_relations(tmp_path: Path) -> None:
    path = tmp_path / "relations.json"
    duplicate = [
        {"subject": "Ana", "relation_type": "works_for", "object": "Acme"},
        {"subject": " ana ", "relation_type": "WORKS_FOR", "object": "acme"},
    ]
    _write(path, duplicate)
    with pytest.raises(EvaluationDataError, match="duplicate"):
        load_relation_dataset(path)


def test_rejects_empty_examples(tmp_path: Path) -> None:
    path = tmp_path / "relations.json"
    path.write_text('{"format_version":1,"name":"x","version":"1","examples":[]}')
    with pytest.raises(EvaluationDataError, match="contain examples"):
        load_relation_dataset(path)
