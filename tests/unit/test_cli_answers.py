import io
import sys

import pytest

from fake_qwen import FakeQwen
from signalscope.cli import build_parser, check_answer_model, main
from signalscope.core.settings import Settings
from signalscope.research.local import Qwen3LocalAnswerGenerator

pytestmark = pytest.mark.anyio


async def run(
    generator: Qwen3LocalAnswerGenerator | None, settings: Settings
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await check_answer_model(settings, out, err, generator=generator)
    return code, out.getvalue(), err.getvalue()


def test_arguments() -> None:
    assert build_parser().parse_args(["check-answer-model"]).command == "check-answer-model"


async def test_summary_with_a_fake_model() -> None:
    fake = FakeQwen()

    code, out, err = await run(Qwen3LocalAnswerGenerator(loader=fake.load), Settings())

    assert (code, err) == (0, "")
    assert out == (
        "Provider: transformers\n"
        "Model: Qwen/Qwen3-4B-Instruct-2507\n"
        "Citations: E1\n"
        "Answer generated: yes\n"
    )
    # One small request, answered from the one piece of evidence.
    [[_, user]] = fake.messages
    assert "[E1]\nTitle: Energy report\n" in user["content"]
    assert fake.load_calls == [("Qwen/Qwen3-4B-Instruct-2507", "cpu", None)]


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ("Offshore wind farms produced more [E1].", "did not return a JSON answer"),
        ('{"text": "They produced more [E2].", "citation_ids": ["E2"]}', "not given: E2"),
    ],
    ids=["not json", "unknown citation"],
)
async def test_bad_answer_fails(reply: str, message: str) -> None:
    fake = FakeQwen()
    fake.reply = reply

    code, out, err = await run(Qwen3LocalAnswerGenerator(loader=fake.load), Settings())

    assert (code, out) == (1, "")
    assert message in err
    assert "produced more" not in err


async def test_needs_local_answers_enabled() -> None:
    code, out, err = await run(None, Settings())

    assert (code, out) == (1, "")
    assert "SIGNALSCOPE_LOCAL_ANSWERS_ENABLED=true" in err


async def test_needs_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "transformers", None)

    code, _, err = await run(None, Settings(local_answers_enabled=True))

    assert code == 1
    assert 'pip install -e ".[local-answers]"' in err


def test_main_needs_local_answers_enabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SIGNALSCOPE_LOCAL_ANSWERS_ENABLED", raising=False)

    assert main(["check-answer-model"]) == 1
    assert "SIGNALSCOPE_LOCAL_ANSWERS_ENABLED=true" in capsys.readouterr().err
