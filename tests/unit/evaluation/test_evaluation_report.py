import json

import pytest

from signalscope.evaluation.evaluation_report import evaluation_report


@pytest.mark.parametrize(
    "task",
    ["embedding_retrieval", "reranking", "structured_extraction", "answer_citation"],
)
def test_serializes_common_envelope_for_each_task(task) -> None:
    report = evaluation_report(
        task=task,
        model="fake-model",
        provider="fake",
        dataset_name="fixed-cases",
        dataset_fingerprint="a" * 64,
        created_at="2026-10-03T10:00:00+00:00",
        environment={"python_version": "3.13.4", "dependencies": {"torch": None}},
        configuration={"limit": 2},
        metrics={"task_specific": {"value": 0.75}},
        timings={"wall_seconds": 1.25},
    )

    decoded = json.loads(json.dumps(report.to_dict()))

    assert decoded["report_version"] == 1
    assert decoded["task"] == task
    assert decoded["dataset"]["fingerprint"] == "a" * 64
    assert decoded["metrics"] == {"task_specific": {"value": 0.75}}


def test_environment_metadata_contains_no_process_environment() -> None:
    report = evaluation_report(
        task="reranking",
        model="fake-model",
        provider="fake",
        dataset_name="fixed-cases",
        dataset_fingerprint="a" * 64,
        created_at="2026-10-03T10:00:00+00:00",
        environment={"platform": "test", "cuda_available": False},
        configuration={},
        metrics={},
        timings={},
    )

    encoded = json.dumps(report.to_dict()).lower()

    assert "token" not in encoded
    assert "password" not in encoded
