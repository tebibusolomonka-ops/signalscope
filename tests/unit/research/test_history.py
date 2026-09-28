import pytest

from signalscope.research.generation import strip_citation_markers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The harbour flooded [E1].", "The harbour flooded."),
        ("Prices rose [E2] [E10] and fell [E3].", "Prices rose and fell."),
        ("No markers here.", "No markers here."),
        ("Keep [note] and E1 as words.", "Keep [note] and E1 as words."),
    ],
)
def test_strip_citation_markers(text: str, expected: str) -> None:
    assert strip_citation_markers(text) == expected
