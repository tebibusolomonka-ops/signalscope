import re
from collections.abc import Sequence

from signalscope.research.evidence import ResearchEvidence
from signalscope.research.generation import GeneratedAnswer, InvalidGeneratedAnswerError

# A citation in the answer text, such as [E2].
CITATION_MARKER = re.compile(r"\[(E[0-9]+)\]")


def validate_citations(
    answer: GeneratedAnswer, evidence: Sequence[ResearchEvidence]
) -> GeneratedAnswer:
    """Check that the answer only cites the evidence it was given.

    citation_ids is the list that counts. It must not be empty or repeat an ID,
    and every ID must belong to the evidence. The text must mark every one of
    those IDs, like [E1], and no others. An answer is never accepted without
    evidence. Error messages name IDs only, never the answer text.
    """
    if not evidence:
        raise InvalidGeneratedAnswerError("The answer model answered without any evidence.")
    allowed = {item.evidence_id for item in evidence}
    cited = list(answer.citation_ids)
    if not cited:
        raise InvalidGeneratedAnswerError("The answer model cited no evidence.")
    if len(set(cited)) != len(cited):
        raise InvalidGeneratedAnswerError("The answer model cited the same evidence twice.")
    unknown = sorted(set(cited) - allowed, key=_order)
    if unknown:
        raise InvalidGeneratedAnswerError(
            f"The answer model cited evidence that it was not given: {', '.join(unknown)}."
        )
    marked = set(CITATION_MARKER.findall(answer.text))
    not_listed = sorted(marked - set(cited), key=_order)
    if not_listed:
        raise InvalidGeneratedAnswerError(
            f"The answer text cites evidence missing from its citation list: "
            f"{', '.join(not_listed)}."
        )
    not_marked = sorted(set(cited) - marked, key=_order)
    if not_marked:
        raise InvalidGeneratedAnswerError(
            f"The answer text does not mark cited evidence: {', '.join(not_marked)}."
        )
    return answer


def _order(citation_id: str) -> int:
    return int(citation_id[1:])
