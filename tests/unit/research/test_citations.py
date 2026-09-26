import uuid

import pytest

from signalscope.research.citations import validate_citations
from signalscope.research.evidence import ResearchEvidence
from signalscope.research.generation import GeneratedAnswer, InvalidGeneratedAnswerError


def evidence(count: int) -> list[ResearchEvidence]:
    return [
        ResearchEvidence(
            evidence_id=f"E{number}",
            document_id=uuid.uuid4(),
            chunk_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            title=None,
            url=None,
            excerpt="An excerpt.",
            text="The full text.",
            chunk_metadata={},
            scores={},
        )
        for number in range(1, count + 1)
    ]


def answer(text: str, *citation_ids: str) -> GeneratedAnswer:
    return GeneratedAnswer(text=text, citation_ids=citation_ids)


def test_valid_answer() -> None:
    given = answer("The river flooded the town [E1].", "E1")

    assert validate_citations(given, evidence(2)) is given


def test_several_citations_in_any_order() -> None:
    given = answer("Rain fell [E3] and the river rose [E1][E3].", "E3", "E1")

    assert validate_citations(given, evidence(3)) is given


@pytest.mark.parametrize(
    ("given", "message"),
    [
        (answer("The river flooded [E3].", "E3"), "not given: E3"),
        (answer("The river flooded [E1] [E2].", "E1"), "missing from its citation list: E2"),
        (answer("The river flooded [E1].", "E1", "E2"), "does not mark cited evidence: E2"),
        (answer("The river flooded [E1].", "E1", "E1"), "same evidence twice"),
        (
            answer(
                "The river flooded.",
            ),
            "cited no evidence",
        ),
        (answer("The river flooded [E9].", "E1"), "missing from its citation list: E9"),
    ],
    ids=[
        "unknown citation",
        "marker not listed",
        "listed but not marked",
        "duplicate",
        "no citations",
        "unknown marker",
    ],
)
def test_bad_citations_are_rejected(given: GeneratedAnswer, message: str) -> None:
    with pytest.raises(InvalidGeneratedAnswerError, match=message):
        validate_citations(given, evidence(2))


def test_no_evidence_means_no_answer() -> None:
    with pytest.raises(InvalidGeneratedAnswerError, match="without any evidence"):
        validate_citations(answer("It flooded [E1].", "E1"), [])


def test_errors_do_not_repeat_the_answer_text() -> None:
    secret = "Some private wording from the model"

    with pytest.raises(InvalidGeneratedAnswerError) as error:
        validate_citations(answer(f"{secret} [E4].", "E4"), evidence(2))

    assert secret not in str(error.value)


def test_unknown_ids_are_listed_in_number_order() -> None:
    with pytest.raises(InvalidGeneratedAnswerError, match="not given: E3, E10"):
        validate_citations(answer("A [E10] B [E3].", "E10", "E3"), evidence(2))
