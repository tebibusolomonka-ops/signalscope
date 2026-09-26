import uuid
from typing import Any

import pytest

from fake_answers import FakeAnswerGenerator
from signalscope.core.errors import ServiceUnavailableError
from signalscope.research.evidence import ResearchEvidence
from signalscope.research.generation import (
    AnswerGeneratorRegistry,
    AnswerGeneratorUnavailableError,
    AnswerRequest,
    DuplicateAnswerGeneratorError,
    GeneratedAnswer,
    InvalidGeneratedAnswerError,
    ResearchAnswerGenerator,
    generate_answer,
)

pytestmark = pytest.mark.anyio


def evidence(number: int) -> ResearchEvidence:
    return ResearchEvidence(
        evidence_id=f"E{number}",
        document_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        title=f"Report {number}",
        url=None,
        excerpt="An excerpt.",
        text="The full text.",
        chunk_metadata={},
        scores={},
    )


def request(count: int = 2) -> AnswerRequest:
    items = tuple(evidence(number) for number in range(1, count + 1))
    return AnswerRequest(question="What happened?", evidence=items, context_text="[E1] ...")


def test_fake_generator_follows_the_protocol() -> None:
    generator: ResearchAnswerGenerator = FakeAnswerGenerator()

    assert (generator.provider_name, generator.model_name) == ("test", "echo")


async def test_answer_from_the_fake_generator() -> None:
    generator = FakeAnswerGenerator()

    answer = await generate_answer(generator, request())

    assert answer == GeneratedAnswer(
        text="Report 1 is relevant [E1]. Report 2 is relevant [E2].",
        citation_ids=("E1", "E2"),
    )
    assert generator.requests[0].question == "What happened?"


async def test_answer_text_is_trimmed_and_citations_become_a_tuple() -> None:
    generator = FakeAnswerGenerator()
    generator.answer = GeneratedAnswer(text="  Yes [E1].  ", citation_ids=["E1"])  # type: ignore[arg-type]

    answer = await generate_answer(generator, request())

    assert answer == GeneratedAnswer(text="Yes [E1].", citation_ids=("E1",))


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (GeneratedAnswer(text="", citation_ids=()), "empty answer"),
        (GeneratedAnswer(text="   ", citation_ids=("E1",)), "empty answer"),
        (GeneratedAnswer(text="Yes.", citation_ids="E1"), "not a list"),  # type: ignore[arg-type]
        (GeneratedAnswer(text="Yes.", citation_ids=("E0",)), "not an evidence ID"),
        (GeneratedAnswer(text="Yes.", citation_ids=("e1",)), "not an evidence ID"),
        (GeneratedAnswer(text="Yes.", citation_ids=("E1 ",)), "not an evidence ID"),
        (GeneratedAnswer(text="Yes.", citation_ids=("[E1]",)), "not an evidence ID"),
        (GeneratedAnswer(text="Yes.", citation_ids=(1,)), "not an evidence ID"),  # type: ignore[arg-type]
        ("Yes [E1].", "did not return an answer"),
    ],
    ids=[
        "empty",
        "blank",
        "citations as text",
        "E0",
        "lower case",
        "trailing space",
        "brackets",
        "number",
        "plain text",
    ],
)
async def test_bad_answers_are_rejected(answer: Any, message: str) -> None:
    generator = FakeAnswerGenerator()
    generator.answer = answer

    with pytest.raises(InvalidGeneratedAnswerError, match=message) as error:
        await generate_answer(generator, request())

    assert "test/echo" in str(error.value)
    assert isinstance(error.value, ServiceUnavailableError)


def test_registry() -> None:
    registry = AnswerGeneratorRegistry()
    generator = FakeAnswerGenerator()

    assert registry.keys() == []
    with pytest.raises(AnswerGeneratorUnavailableError, match="No answer model"):
        registry.only()
    registry.register(generator)

    assert registry.get("test", "echo") is generator
    assert registry.only() is generator
    with pytest.raises(DuplicateAnswerGeneratorError, match="already registered"):
        registry.register(FakeAnswerGenerator())
    with pytest.raises(AnswerGeneratorUnavailableError, match="test/other is not configured"):
        registry.get("test", "other")
    registry.register(FakeAnswerGenerator(model_name="other"))
    with pytest.raises(AnswerGeneratorUnavailableError, match="More than one"):
        registry.only()
