import json
from datetime import UTC, datetime

import pytest

from signalscope.evaluation.answer_benchmark import benchmark_answers, load_answer_dataset
from signalscope.research.generation import GeneratedAnswer


class FakeGenerator:
    provider_name = "fake"
    model_name = "fake-qwen"

    async def generate(self, request):
        return GeneratedAnswer("The port is open [E1].", ("E1",))


@pytest.mark.anyio
async def test_answer_benchmark_report(tmp_path) -> None:
    path = tmp_path / "answers.json"
    path.write_text(
        json.dumps(
            {
                "name": "answers",
                "prompt_config_version": "1",
                "cases": [
                    {
                        "key": "q1",
                        "question": "Is the port open?",
                        "evidence": [{"id": "E1", "text": "The port is open."}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = await benchmark_answers(
        FakeGenerator(),
        load_answer_dataset(path),
        "a" * 64,
        timestamp=datetime(2026, 10, 3, tzinfo=UTC),
    )
    assert report.metrics == {
        "json_parse_successes": 1,
        "citation_validation_successes": 1,
        "invalid_citation_count": 0,
        "missing_citation_count": 0,
    }
