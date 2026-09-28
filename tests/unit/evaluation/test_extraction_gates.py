from typing import Any

import pytest

from signalscope.evaluation.extraction.gates import (
    ExtractionGate,
    parse_extraction_gates,
)
from signalscope.evaluation.gates import QualityGateError


def test_partial_rules() -> None:
    gates = parse_extraction_gates(
        {"event": {"precision": 0.7, "f1": 1}, "relation": {"recall": 0}}
    )

    assert gates == [
        ExtractionGate("event", "precision", 0.7),
        ExtractionGate("event", "f1", 1.0),
        ExtractionGate("relation", "recall", 0.0),
    ]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({}, "at least one mode"),
        ([], "at least one mode"),
        ({"entity": {"f1": 0.5}}, "unknown mode 'entity'"),
        ({"event": {"accuracy": 0.5}}, "not a known metric"),
        ({"event": {"f1": "high"}}, "between 0 and 1"),
        ({"event": {"f1": True}}, "between 0 and 1"),
        ({"event": {"f1": 1.2}}, "between 0 and 1"),
        ({"event": {"f1": -0.1}}, "between 0 and 1"),
        ({"event": {}}, "object of metrics"),
    ],
    ids=[
        "empty",
        "not an object",
        "unknown mode",
        "unknown metric",
        "not a number",
        "bool",
        "above one",
        "below zero",
        "no metrics",
    ],
)
def test_invalid_gates(raw: Any, message: str) -> None:
    with pytest.raises(QualityGateError, match=message):
        parse_extraction_gates(raw)
