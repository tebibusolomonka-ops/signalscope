import codecs
import re

from signalscope.parsing.content_type import content_charset
from signalscope.parsing.types import DocumentParsingError, ParsedDocument

# Old Windows text files often use this. Five of its bytes have no meaning, so
# binary data usually fails to decode instead of turning into nonsense text.
FALLBACK_ENCODING = "windows-1252"
# Tab, line feed, vertical tab, form feed and carriage return are normal in text.
ALLOWED_CONTROL_CHARACTERS = frozenset("\t\n\v\f\r")
# More control characters than this share of the text means the data is binary.
MAX_CONTROL_SHARE = 0.01
GENERIC_FILE_NAMES = frozenset({"document", "download", "file", "text", "untitled"})
# Names like "12345" or "3f2a9c1e4b5d6a7f" are IDs, not titles.
ID_LIKE_NAME = re.compile(r"\d+|[0-9a-f-]{16,}")


class PlainTextParser:
    """Reads text/plain documents.

    Line breaks become \\n. Other whitespace is kept as it is, so paragraphs and
    indentation survive.
    """

    def parse(
        self,
        data: bytes,
        *,
        content_type: str,
        filename: str | None = None,
        source_url: str | None = None,
    ) -> ParsedDocument:
        text, encoding = _decode(data, content_charset(content_type))
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            text = ""
        return ParsedDocument(
            text=text, title=title_from_filename(filename), metadata={"encoding": encoding}
        )


def title_from_filename(filename: str | None) -> str | None:
    """Use a file name as a title, unless it says nothing about the content."""
    if filename is None:
        return None
    # Uploads can send a full path from either Windows or Unix.
    name = re.split(r"[\\/]", filename)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name[1:] else name
    title = stem.strip()
    if not any(character.isalpha() for character in title):
        return None
    if title.lower() in GENERIC_FILE_NAMES or ID_LIKE_NAME.fullmatch(title.lower()):
        return None
    return title


def _decode(data: bytes, declared_charset: str | None) -> tuple[str, str]:
    # An unknown charset arrives as None, so the usual encodings are tried.
    # utf-8-sig also removes a byte order mark at the start.
    encodings = ["utf-8-sig", FALLBACK_ENCODING]
    if declared_charset is not None and declared_charset != "utf-8":
        encodings.insert(0, declared_charset)
    for encoding in encodings:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _looks_binary(text):
            break
        name = "utf-8" if encoding == "utf-8-sig" else codecs.lookup(encoding).name
        return text.removeprefix("﻿"), name
    raise DocumentParsingError("Document is not readable text.")


def _looks_binary(text: str) -> bool:
    if "\x00" in text:
        return True
    controls = sum(
        1
        for character in text
        if ord(character) < 32 and character not in ALLOWED_CONTROL_CHARACTERS
    )
    return controls > len(text) * MAX_CONTROL_SHARE
