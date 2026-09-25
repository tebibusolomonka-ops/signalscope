import pytest

from signalscope.parsing.plain_text import PlainTextParser, title_from_filename
from signalscope.parsing.types import DocumentParsingError, ParsedDocument


def parse(
    data: bytes, content_type: str = "text/plain", filename: str | None = None
) -> ParsedDocument:
    return PlainTextParser().parse(data, content_type=content_type, filename=filename)


def test_utf8_text() -> None:
    document = parse("Café and naïve – ünïcode\n".encode())

    assert document.text == "Café and naïve – ünïcode\n"
    assert document.metadata == {"encoding": "utf-8"}
    assert document.title is None
    assert document.language is None


def test_byte_order_mark_is_removed() -> None:
    document = parse(b"\xef\xbb\xbfHello")

    assert document.text == "Hello"
    assert document.metadata == {"encoding": "utf-8"}


def test_line_breaks_become_line_feeds() -> None:
    assert parse(b"one\r\ntwo\rthree\nfour").text == "one\ntwo\nthree\nfour"


def test_whitespace_and_paragraphs_are_kept() -> None:
    text = "Title\n\n\n  Indented line\twith a tab.\n\nSecond  paragraph.  \n"

    assert parse(text.encode()).text == text


@pytest.mark.parametrize("data", [b"", b"   ", b"\n\n\t \r\n"])
def test_empty_or_blank_text_is_empty(data: bytes) -> None:
    assert parse(data).text == ""


def test_declared_charset_is_used() -> None:
    document = parse(b"caf\xe9", content_type="text/plain; charset=ISO-8859-1")

    assert document.text == "café"
    assert document.metadata == {"encoding": "iso8859-1"}


def test_declared_utf8_charset() -> None:
    assert parse("Ω".encode(), content_type='text/plain; charset="utf-8"').text == "Ω"


def test_unknown_charset_is_ignored() -> None:
    document = parse("Ω".encode(), content_type="text/plain; charset=made-up")

    assert document.text == "Ω"
    assert document.metadata == {"encoding": "utf-8"}


def test_old_windows_text_is_read() -> None:
    # 0x93 and 0x94 are curly quotes in Windows-1252 and invalid in UTF-8.
    document = parse(b"\x93Quoted\x94 caf\xe9")

    assert document.text == "\u201cQuoted\u201d café"
    assert document.metadata == {"encoding": "cp1252"}


@pytest.mark.parametrize(
    "data",
    [
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        b"text with a \x00 byte",
        b"%PDF-1.7\n\x81\x8d\x8f\x90\x9d",
        bytes(range(1, 32)) * 4,
    ],
)
def test_binary_data_is_rejected(data: bytes) -> None:
    with pytest.raises(DocumentParsingError, match="Document is not readable text."):
        parse(data)


def test_a_few_control_characters_are_allowed() -> None:
    text = "Form feed between pages\f" + "x" * 200

    assert parse(text.encode()).text == text


@pytest.mark.parametrize(
    ("filename", "title"),
    [
        ("Quarterly notes.txt", "Quarterly notes"),
        ("C:\\Users\\jane\\Meeting notes.txt", "Meeting notes"),
        ("uploads/interview-2024.txt", "interview-2024"),
        ("README", "README"),
        (".profile", ".profile"),
        ("document.txt", None),
        ("Untitled.TXT", None),
        ("12345.txt", None),
        ("3f2a9c1e-4b5d-6a7f-8e9d-0c1b2a3f4e5d.txt", None),
        ("  .txt", None),
        (None, None),
    ],
)
def test_title_from_filename(filename: str | None, title: str | None) -> None:
    assert title_from_filename(filename) == title


def test_parser_uses_the_filename_title() -> None:
    assert parse(b"Hello", filename="Greetings.txt").title == "Greetings"
