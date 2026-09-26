import json
from pathlib import Path
from typing import Any

import pytest

from signalscope.evaluation.gates import (
    GateResult,
    QualityGate,
    QualityGateError,
    check_gates,
    format_gate_results,
    load_quality_gates,
    parse_quality_gates,
)
from signalscope.evaluation.metrics import MetricsSummary
from signalscope.evaluation.retrieval import LatencySummary, RetrievalReport

MODES = ("lexical", "semantic", "hybrid", "reranked")


def report(mode: str, recall: float, mrr: float) -> RetrievalReport:
    return RetrievalReport(
        mode=mode,
        dataset="smoke",
        ks=(10,),
        metrics=MetricsSummary(query_count=1, recall={10: recall}, mrr={10: mrr}, ndcg={10: 0.5}),
        queries=(),
        latency=LatencySummary(1.0, 1.0, 1.0),
    )


def test_parse_gates() -> None:
    gates = parse_quality_gates(
        {"hybrid": {"recall@10": 0.8, "mrr@10": 1}, "reranked": {"ndcg@5": 0}}, MODES
    )

    assert gates == [
        QualityGate("hybrid", "recall", 10, 0.8),
        QualityGate("hybrid", "mrr", 10, 1.0),
        QualityGate("reranked", "ndcg", 5, 0.0),
    ]
    assert gates[0].label == "Hybrid Recall@10"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({}, "at least one mode"),
        ([], "at least one mode"),
        ({"fuzzy": {"recall@10": 0.5}}, "unknown mode 'fuzzy'"),
        ({"hybrid": {}}, "object of metrics"),
        ({"hybrid": {"precision@10": 0.5}}, "not a known metric"),
        ({"hybrid": {"recall": 0.5}}, "not a known metric"),
        ({"hybrid": {"recall@0": 0.5}}, "k between 1 and 50"),
        ({"hybrid": {"recall@51": 0.5}}, "k between 1 and 50"),
        ({"hybrid": {"recall@10": 1.5}}, "minimum between 0 and 1"),
        ({"hybrid": {"recall@10": -0.1}}, "minimum between 0 and 1"),
        ({"hybrid": {"recall@10": "high"}}, "minimum between 0 and 1"),
        ({"hybrid": {"recall@10": True}}, "minimum between 0 and 1"),
    ],
    ids=[
        "empty",
        "not an object",
        "unknown mode",
        "no metrics",
        "unknown metric",
        "no k",
        "k zero",
        "k too large",
        "above one",
        "below zero",
        "text",
        "boolean",
    ],
)
def test_invalid_gates(raw: Any, message: str) -> None:
    with pytest.raises(QualityGateError, match=message):
        parse_quality_gates(raw, MODES)


def test_load_file(tmp_path: Path) -> None:
    path = tmp_path / "gates.json"
    path.write_text(json.dumps({"lexical": {"mrr@10": 0.25}}), encoding="utf-8")

    assert load_quality_gates(path, MODES) == [QualityGate("lexical", "mrr", 10, 0.25)]


def test_load_bad_files(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")

    with pytest.raises(QualityGateError, match="not valid JSON"):
        load_quality_gates(broken, MODES)
    with pytest.raises(QualityGateError, match="Cannot read"):
        load_quality_gates(tmp_path / "missing.json", MODES)


def test_passed_missed_and_not_run() -> None:
    gates = [
        QualityGate("hybrid", "recall", 10, 0.8),
        QualityGate("hybrid", "mrr", 10, 0.6),
        QualityGate("reranked", "mrr", 10, 0.1),
    ]

    results = check_gates(gates, [report("hybrid", recall=0.8, mrr=0.5)])

    assert [(result.value, result.passed) for result in results] == [
        (0.8, True),
        (0.5, False),
        (None, False),
    ]


def test_all_passed() -> None:
    results = check_gates(
        [QualityGate("lexical", "recall", 10, 0.5)], [report("lexical", recall=0.9, mrr=0.1)]
    )

    assert all(result.passed for result in results)


def test_output_only_says_passed_or_missed() -> None:
    results = [
        GateResult(QualityGate("hybrid", "recall", 10, 0.8), 0.85),
        GateResult(QualityGate("reranked", "ndcg", 5, 0.5), None),
    ]

    assert format_gate_results(results) == (
        "\n"
        "Quality gates\n"
        "Hybrid Recall@10: 0.850, minimum 0.800, passed\n"
        "Reranked nDCG@5: not run, minimum 0.500, missed\n"
        "Gates missed: 1 of 2\n"
    )
