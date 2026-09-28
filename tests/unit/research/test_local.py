"""The local Qwen answer model, with a fake in place of Transformers.

Nothing here downloads or loads model files.
"""

import asyncio
import json
import sys
import threading
import types
import uuid
from pathlib import Path
from typing import Any

import pytest

from fake_qwen import FakeQwen
from signalscope.core.errors import ServiceUnavailableError
from signalscope.research.evidence import ResearchEvidence
from signalscope.research.generation import (
    AnswerRequest,
    ConversationTurn,
    GeneratedAnswer,
    InvalidGeneratedAnswerError,
    generate_answer,
)
from signalscope.research.local import (
    LocalAnswersNotInstalledError,
    Qwen3LocalAnswerGenerator,
    load_qwen,
)

pytestmark = pytest.mark.anyio


def evidence(number: int, title: str | None, text: str) -> ResearchEvidence:
    return ResearchEvidence(
        evidence_id=f"E{number}",
        document_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        title=title,
        url="https://example.org/private-link",
        excerpt="Short excerpt.",
        text=text,
        chunk_metadata={"page_number": 7},
        scores={"hybrid": 0.5},
    )


REQUEST = AnswerRequest(
    question="What flooded?",
    evidence=(
        evidence(1, "Harbour Report", "Water flooded the harbour district."),
        evidence(2, None, "Energy prices rose."),
    ),
    context_text="not used by this model",
)


def generator_with(
    fake: FakeQwen | None = None, **options: Any
) -> tuple[Qwen3LocalAnswerGenerator, FakeQwen]:
    fake = fake or FakeQwen()
    return Qwen3LocalAnswerGenerator(loader=fake.load, **options), fake


def test_identity_and_defaults() -> None:
    generator, fake = generator_with()

    assert (generator.provider_name, generator.model_name) == (
        "transformers",
        "Qwen/Qwen3-4B-Instruct-2507",
    )
    assert (generator.device, generator.max_new_tokens, generator.cache_dir) == ("cpu", 512, None)
    assert fake.load_calls == []


@pytest.mark.parametrize("tokens", [0, -1])
def test_max_new_tokens_must_be_positive(tokens: int) -> None:
    with pytest.raises(ValueError, match="max_new_tokens"):
        generator_with(max_new_tokens=tokens)


async def test_model_is_loaded_lazily_once_with_the_device(tmp_path: Path) -> None:
    generator, fake = generator_with(device="cuda", cache_dir=tmp_path)

    await asyncio.gather(*(generator.generate(REQUEST) for _ in range(3)))

    assert fake.load_calls == [("Qwen/Qwen3-4B-Instruct-2507", "cuda", tmp_path)]


async def test_chat_messages_hold_only_the_question_and_evidence() -> None:
    generator, fake = generator_with()

    await generator.generate(REQUEST)

    [[system, user]] = fake.messages
    assert system["role"] == "system"
    for rule in ("only the evidence", "outside knowledge", "[E1]", "only a JSON object"):
        assert rule in system["content"]
    assert user == {
        "role": "user",
        "content": "Evidence:\n\n"
        "[E1]\nTitle: Harbour Report\nText: Water flooded the harbour district.\n\n"
        "[E2]\nTitle: (no title)\nText: Energy prices rose.\n\n"
        "Question: What flooded?",
    }
    # Nothing outside the evidence text reaches the model.
    assert "private-link" not in user["content"]
    assert "page_number" not in user["content"]
    assert fake.template_options == [{"tokenize": False, "add_generation_prompt": True}]


async def test_generation_is_deterministic_and_off_the_event_loop() -> None:
    generator, fake = generator_with(max_new_tokens=128)

    await generator.generate(REQUEST)

    [options] = fake.generate_options
    assert (options["do_sample"], options["max_new_tokens"]) == (False, 128)
    assert options["input_ids"] == [[101, 102, 103]]
    assert fake.input_devices == ["cpu"]
    assert fake.threads != [threading.current_thread().name]


async def test_valid_json_becomes_an_answer() -> None:
    generator, fake = generator_with()
    fake.reply = '  {"text": "The harbour flooded [E1].", "citation_ids": ["E1"]}\n'

    answer = await generate_answer(generator, REQUEST)

    assert answer == GeneratedAnswer(text="The harbour flooded [E1].", citation_ids=("E1",))


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ("The harbour flooded [E1].", "did not return a JSON answer"),
        ('Sure! {"text": "x [E1]", "citation_ids": ["E1"]}', "did not return a JSON answer"),
        ('```json\n{"text": "x [E1]", "citation_ids": ["E1"]}\n```', "not return a JSON answer"),
        ('["E1"]', "without exactly text and citation_ids"),
        ('{"text": "x [E1]"}', "without exactly text and citation_ids"),
        ('{"text": "x", "citation_ids": [], "notes": "extra"}', "without exactly text"),
        ('{"text": 3, "citation_ids": ["E1"]}', "fields of the wrong type"),
        ('{"text": "x [E1]", "citation_ids": "E1"}', "fields of the wrong type"),
        ('{"text": "x [E1]", "citation_ids": [1]}', "citations that are not text"),
    ],
    ids=[
        "plain text",
        "chatter around json",
        "markdown fence",
        "list",
        "missing field",
        "extra field",
        "text not a string",
        "ids not a list",
        "id not a string",
    ],
)
async def test_bad_output_fails_safely(reply: str, message: str) -> None:
    generator, fake = generator_with()
    fake.reply = reply

    with pytest.raises(InvalidGeneratedAnswerError, match=message) as error:
        await generator.generate(REQUEST)

    assert "harbour" not in str(error.value)
    assert isinstance(error.value, ServiceUnavailableError)


def test_missing_library_gives_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # None in sys.modules makes the import fail, as if the extra were not installed.
    monkeypatch.setitem(sys.modules, "transformers", None)

    with pytest.raises(LocalAnswersNotInstalledError, match="local-answers") as error:
        load_qwen("Qwen/Qwen3-4B-Instruct-2507", "cpu", None)

    assert isinstance(error.value, ServiceUnavailableError)


async def test_missing_library_surfaces_on_first_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "transformers", None)

    with pytest.raises(LocalAnswersNotInstalledError):
        await Qwen3LocalAnswerGenerator().generate(REQUEST)


def test_loader_uses_the_auto_classes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    class FakeModel:
        def to(self, device: str) -> None:
            calls.append(("to", device, {}))

        def eval(self) -> None:
            calls.append(("eval", "", {}))

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(model: str, **options: Any) -> str:
            calls.append(("tokenizer", model, options))
            return "tokenizer"

    class AutoModelForCausalLM:
        @staticmethod
        def from_pretrained(model: str, **options: Any) -> FakeModel:
            calls.append(("model", model, options))
            return FakeModel()

    # A stand-in for the library, so nothing is downloaded.
    module = types.ModuleType("transformers")
    module.AutoTokenizer = AutoTokenizer  # type: ignore[attr-defined]
    module.AutoModelForCausalLM = AutoModelForCausalLM  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "transformers", module)

    tokenizer, _ = load_qwen("Qwen/Qwen3-4B-Instruct-2507", "cpu", tmp_path)

    assert tokenizer == "tokenizer"
    assert calls == [
        ("tokenizer", "Qwen/Qwen3-4B-Instruct-2507", {"cache_dir": tmp_path}),
        (
            "model",
            "Qwen/Qwen3-4B-Instruct-2507",
            {"cache_dir": tmp_path, "torch_dtype": "auto"},
        ),
        ("to", "cpu", {}),
        ("eval", "", {}),
    ]


def test_default_fake_answer_is_valid_json() -> None:
    fake = FakeQwen()
    fake.messages.append([{"role": "user", "content": "[E2] and [E1] and [E2]"}])

    assert json.loads(fake._answer())["citation_ids"] == ["E2", "E1"]


async def test_history_is_marked_as_context() -> None:
    generator, fake = generator_with()
    request = AnswerRequest(
        question="And the port?",
        evidence=REQUEST.evidence[:1],
        context_text="",
        history=(ConversationTurn("What flooded?", "The harbour flooded."),),
    )

    await generator.generate(request)

    [[system, user]] = fake.messages
    assert "context only, not evidence" in system["content"]
    assert user["content"].startswith(
        "Earlier conversation (context only, not evidence):\n\n"
        "Question: What flooded?\nAnswer: The harbour flooded.\n\n"
        "Evidence:\n\n[E1]\n"
    )
    assert user["content"].endswith("Question: And the port?")
