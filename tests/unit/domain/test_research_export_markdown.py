import uuid
from datetime import UTC, datetime

from signalscope.domain.research.export import ResearchSessionExport, session_markdown
from signalscope.domain.research.schemas import (
    ResearchSessionRead,
    ResearchTurnRead,
    TurnEvidenceRead,
)
from signalscope.research.evidence import ResearchMode

CREATED = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)
SESSION = ResearchSessionRead(
    id=uuid.UUID(int=1),
    title="Harbour floods",
    retrieval_mode=ResearchMode.HYBRID,
    source_id=None,
    organization_id=None,
    created_at=CREATED,
    updated_at=CREATED,
)


def evidence(number: int, url: str | None = None) -> TurnEvidenceRead:
    return TurnEvidenceRead(
        evidence_id=f"E{number}",
        document_id=uuid.UUID(int=10 + number),
        chunk_id=uuid.UUID(int=20 + number),
        source_id=uuid.UUID(int=30),
        title=f"Report {number}",
        url=url,
        excerpt=f"Excerpt {number}.",
        chunk_metadata={},
    )


def turn(sequence: int, answer: str | None, *items: TurnEvidenceRead) -> ResearchTurnRead:
    cited = [item.evidence_id for item in items] if answer else []
    return ResearchTurnRead(
        id=uuid.UUID(int=100 + sequence),
        sequence=sequence,
        question=f"Question {sequence}?",
        answer=answer,
        citation_ids=cited,
        citations=[item for item in items if item.evidence_id in cited],
        evidence=list(items),
        created_at=CREATED,
    )


def test_empty_session() -> None:
    assert session_markdown(ResearchSessionExport(session=SESSION, turns=[])) == (
        "# Harbour floods\n"
        "\n"
        "Search mode: hybrid\n"
        "Source: all sources\n"
        "Created: 2026-03-04T09:00:00+00:00\n"
        "\n"
        "No questions yet.\n"
    )


def test_turns_keep_their_citation_ids() -> None:
    export = ResearchSessionExport(
        session=SESSION,
        turns=[
            turn(
                1,
                "The harbour flooded [E1] [E2].",
                evidence(1, "https://example.org/a"),
                evidence(2),
            ),
            turn(2, None),
        ],
    )

    text = session_markdown(export)

    assert text == session_markdown(export)
    assert text.endswith(
        "## Turn 1\n"
        "\n"
        "Question: Question 1?\n"
        "\n"
        "Answer: The harbour flooded [E1] [E2].\n"
        "\n"
        "Citations: E1, E2\n"
        "\n"
        "### Evidence\n"
        "\n"
        "- [E1] Report 1 (https://example.org/a): Excerpt 1.\n"
        "- [E2] Report 2: Excerpt 2.\n"
        "\n"
        "## Turn 2\n"
        "\n"
        "Question: Question 2?\n"
        "\n"
        "Answer: (no answer)\n"
        "\n"
        "### Evidence\n"
        "\n"
        "No evidence was found.\n"
    )
