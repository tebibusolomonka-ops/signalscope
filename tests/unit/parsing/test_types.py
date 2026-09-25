import dataclasses

import pytest

from signalscope.core.errors import SignalScopeError
from signalscope.parsing.types import (
    DocumentParser,
    DocumentParsingError,
    MetadataValue,
    ParsedDocument,
    UnsupportedDocumentTypeError,
)


def test_defaults() -> None:
    document = ParsedDocument(text="Hello")

    assert (document.text, document.title, document.language) == ("Hello", None, None)
    assert dict(document.metadata) == {}


def test_fields_cannot_be_changed() -> None:
    document = ParsedDocument(text="Hello", title="Greeting")

    with pytest.raises(dataclasses.FrozenInstanceError):
        document.text = "Bye"  # type: ignore[misc]


def test_metadata_cannot_be_changed() -> None:
    metadata: dict[str, MetadataValue] = {"author": "Jane", "page_count": 3}
    document = ParsedDocument(text="", metadata=metadata)

    with pytest.raises(TypeError):
        document.metadata["author"] = "Someone else"  # type: ignore[index]

    # Changing the original dict does not change the document either.
    metadata["author"] = "Someone else"
    assert document.metadata == {"author": "Jane", "page_count": 3}


def test_fields_must_be_named() -> None:
    with pytest.raises(TypeError):
        ParsedDocument("Hello")  # type: ignore[call-arg]


class UpperCaseParser:
    """A fake parser, to show the protocol is easy to implement."""

    def parse(
        self,
        data: bytes,
        *,
        content_type: str,
        filename: str | None = None,
        source_url: str | None = None,
    ) -> ParsedDocument:
        if not data:
            raise DocumentParsingError("Document is empty.")
        return ParsedDocument(
            text=data.decode().upper(),
            title=filename,
            metadata={"content_type": content_type, "source_url": source_url or ""},
        )


def test_fake_parser_follows_the_protocol() -> None:
    parser: DocumentParser = UpperCaseParser()

    document = parser.parse(
        b"hello",
        content_type="text/plain",
        filename="note.txt",
        source_url="https://example.com/note.txt",
    )

    assert document.text == "HELLO"
    assert document.title == "note.txt"
    assert document.metadata == {
        "content_type": "text/plain",
        "source_url": "https://example.com/note.txt",
    }


def test_parser_errors() -> None:
    with pytest.raises(DocumentParsingError, match="Document is empty."):
        UpperCaseParser().parse(b"", content_type="text/plain")


def test_error_messages() -> None:
    assert str(DocumentParsingError()) == "Document could not be parsed."
    assert str(UnsupportedDocumentTypeError()) == "Document type is not supported."
    assert str(DocumentParsingError("PDF is encrypted.")) == "PDF is encrypted."


def test_unsupported_type_is_a_parsing_error() -> None:
    # Callers can catch every parsing problem with one except clause.
    assert issubclass(UnsupportedDocumentTypeError, DocumentParsingError)
    assert issubclass(DocumentParsingError, SignalScopeError)
