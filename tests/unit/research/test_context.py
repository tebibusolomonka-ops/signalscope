import uuid
from typing import Any

from signalscope.research.context import context_text
from signalscope.research.evidence import ResearchEvidence


def evidence(number: int, **values: Any) -> ResearchEvidence:
    fields: dict[str, Any] = {
        "evidence_id": f"E{number}",
        "document_id": uuid.uuid4(),
        "chunk_id": uuid.uuid4(),
        "source_id": uuid.uuid4(),
        "title": f"Report {number}",
        "url": None,
        "excerpt": "An excerpt.",
        "text": f"  Full text {number}.  ",
        "chunk_metadata": {},
        "scores": {},
    }
    return ResearchEvidence(**(fields | values))


def test_context_blocks() -> None:
    text = context_text(
        [
            evidence(1, url="https://example.test/a", chunk_metadata={"page_number": 2}),
            evidence(2, title=None),
        ]
    )

    assert text == (
        "[E1]\n"
        "Title: Report 1\n"
        "URL: https://example.test/a\n"
        "Page: 2\n"
        "Text: Full text 1.\n"
        "\n"
        "[E2]\n"
        "Title: (no title)\n"
        "Text: Full text 2."
    )


def test_no_evidence_gives_no_context() -> None:
    assert context_text([]) == ""
