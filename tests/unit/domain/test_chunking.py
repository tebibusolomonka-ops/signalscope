import hashlib
import random

import pytest

from signalscope.domain.documents.chunking import TextChunk, chunk_text

# Small sizes keep the test texts readable.
SMALL = {"max_chars": 50, "overlap_chars": 10, "min_chars": 25}


def check_offsets(text: str, chunks: list[TextChunk]) -> None:
    assert [chunk.position for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert chunk.text == text[chunk.start_char : chunk.end_char]
        assert chunk.text
        assert chunk.text == chunk.text.strip()
        assert chunk.text_hash == hashlib.sha256(chunk.text.encode()).hexdigest()


def covered(text: str, chunks: list[TextChunk]) -> bool:
    """Whether every non-whitespace character is in at least one chunk."""
    inside = [False] * len(text)
    for chunk in chunks:
        for index in range(chunk.start_char, chunk.end_char):
            inside[index] = True
    return all(inside[index] for index, char in enumerate(text) if not char.isspace())


@pytest.mark.parametrize("text", ["", "   ", "\n\n\t \n"])
def test_empty_text_has_no_chunks(text: str) -> None:
    assert chunk_text(text) == []


def test_short_text_is_one_chunk() -> None:
    [chunk] = chunk_text("Climate policy notes.")

    assert chunk == TextChunk(
        position=0,
        text="Climate policy notes.",
        start_char=0,
        end_char=21,
        text_hash=hashlib.sha256(b"Climate policy notes.").hexdigest(),
    )


def test_surrounding_whitespace_is_left_out() -> None:
    text = "\n\n  Hello world.  \n"

    [chunk] = chunk_text(text)

    assert (chunk.text, chunk.start_char, chunk.end_char) == ("Hello world.", 4, 16)


def test_default_sizes() -> None:
    text = " ".join(f"word{number}" for number in range(1000))

    chunks = chunk_text(text)

    check_offsets(text, chunks)
    assert all(len(chunk.text) <= 1200 for chunk in chunks)
    assert all(len(chunk.text) >= 600 for chunk in chunks[:-1])
    assert covered(text, chunks)


def test_chunks_end_at_paragraph_breaks() -> None:
    paragraphs = [f"Paragraph {number} " + "x" * 20 + "." for number in range(8)]
    text = "\n\n".join(paragraphs)

    chunks = chunk_text(text, **SMALL)

    check_offsets(text, chunks)
    for chunk in chunks[:-1]:
        assert text[chunk.end_char : chunk.end_char + 2] == "\n\n"
    assert covered(text, chunks)


def test_line_breaks_come_before_other_whitespace() -> None:
    text = "\n".join(f"line {number} with some words" for number in range(10))

    chunks = chunk_text(text, **SMALL)

    check_offsets(text, chunks)
    for chunk in chunks[:-1]:
        assert text[chunk.end_char] == "\n"


def test_whitespace_is_used_when_there_are_no_line_breaks() -> None:
    text = " ".join(["alpha", "beta", "gamma", "delta"] * 10)

    chunks = chunk_text(text, **SMALL)

    check_offsets(text, chunks)
    for chunk in chunks[:-1]:
        assert text[chunk.end_char] == " "
        assert len(chunk.text) <= 50
    assert covered(text, chunks)


def test_long_word_is_cut() -> None:
    text = "x" * 120

    chunks = chunk_text(text, **SMALL)

    assert [(chunk.start_char, chunk.end_char) for chunk in chunks] == [
        (0, 50),
        (40, 90),
        (80, 120),
    ]
    check_offsets(text, chunks)


def test_chunks_overlap() -> None:
    text = " ".join(f"w{number:03d}" for number in range(100))

    chunks = chunk_text(text, **SMALL)

    for previous, following in zip(chunks, chunks[1:], strict=False):
        assert following.start_char < previous.end_char
        assert previous.end_char - following.start_char <= 10
        # The overlap starts at the beginning of a word.
        assert text[following.start_char - 1] == " "


def test_early_break_does_not_make_a_tiny_chunk() -> None:
    text = "Title\n\n" + " ".join(["word"] * 40)

    first = chunk_text(text, **SMALL)[0]

    assert first.start_char == 0
    assert len(first.text) >= 25


def test_unicode_offsets() -> None:
    text = ("Klimapolitik für Städte 🌍 東京の気候政策 " * 6).strip()

    chunks = chunk_text(text, **SMALL)

    assert len(chunks) > 1
    check_offsets(text, chunks)
    assert covered(text, chunks)


def test_text_is_not_changed() -> None:
    text = "Line one\r\n\r\nLine  two\twith tab\r\n" * 5

    chunks = chunk_text(text, **SMALL)

    check_offsets(text, chunks)
    assert "\r\n" in "".join(chunk.text for chunk in chunks)


def test_random_texts() -> None:
    randomizer = random.Random(20260501)
    words = ["a", "bb", "climate", "policy", "\n", "\n\n", "  ", "Städte", "x" * 70]
    for _ in range(50):
        text = " ".join(randomizer.choice(words) for _ in range(randomizer.randint(0, 200)))

        chunks = chunk_text(text, **SMALL)

        check_offsets(text, chunks)
        assert covered(text, chunks)
        assert all(len(chunk.text) <= 50 for chunk in chunks)


def test_chunking_is_deterministic() -> None:
    text = " ".join(f"word{number}" for number in range(500))

    assert chunk_text(text) == chunk_text(text)


@pytest.mark.parametrize(
    "sizes",
    [
        {"max_chars": 50, "overlap_chars": 25, "min_chars": 25},
        {"max_chars": 50, "overlap_chars": 10, "min_chars": 60},
        {"max_chars": 50, "overlap_chars": -1, "min_chars": 25},
    ],
)
def test_invalid_sizes_are_rejected(sizes: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="chunk sizes"):
        chunk_text("text", **sizes)
