import pytest

from signalscope.parsing.docx_document import DOCX_CONTENT_TYPE, DocxDocumentParser
from signalscope.parsing.html_document import HtmlDocumentParser
from signalscope.parsing.json_document import JsonParser
from signalscope.parsing.pdf_document import PdfDocumentParser
from signalscope.parsing.plain_text import PlainTextParser
from signalscope.parsing.registry import ParserRegistry, create_default_parser_registry
from signalscope.parsing.types import DocumentParsingError, UnsupportedDocumentTypeError


def test_registered_parser_is_found() -> None:
    registry = ParserRegistry()
    parser = PlainTextParser()
    registry.register("text/plain", parser)

    assert registry.get("text/plain") is parser


@pytest.mark.parametrize(
    "content_type", ["text/plain; charset=utf-8", "Text/Plain", "  text/plain ;format=flowed"]
)
def test_content_types_are_normalized(content_type: str) -> None:
    registry = ParserRegistry()
    parser = PlainTextParser()
    registry.register("TEXT/PLAIN; charset=ascii", parser)

    assert registry.get(content_type) is parser


def test_registering_twice_is_an_error() -> None:
    registry = ParserRegistry()
    registry.register("text/plain", PlainTextParser())

    with pytest.raises(ValueError, match="already registered for text/plain"):
        registry.register("text/plain; charset=utf-8", PlainTextParser())


def test_empty_content_type_cannot_be_registered() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        ParserRegistry().register(" ; charset=utf-8", PlainTextParser())


def test_unknown_type_is_unsupported() -> None:
    registry = ParserRegistry()

    with pytest.raises(UnsupportedDocumentTypeError, match="No parser is available for image/png."):
        registry.get("image/png")
    with pytest.raises(UnsupportedDocumentTypeError, match="an empty content type"):
        registry.get("")


def test_long_unknown_type_is_cut_in_the_message() -> None:
    with pytest.raises(UnsupportedDocumentTypeError) as error:
        ParserRegistry().get("x/" + "y" * 500)

    assert len(str(error.value)) < 150


def test_unsupported_type_is_a_parsing_error() -> None:
    with pytest.raises(DocumentParsingError):
        ParserRegistry().get("application/zip")


@pytest.mark.parametrize(
    ("content_type", "parser_type"),
    [
        ("text/plain", PlainTextParser),
        ("application/json", JsonParser),
        ("text/html; charset=utf-8", HtmlDocumentParser),
        ("application/xhtml+xml", HtmlDocumentParser),
        ("application/pdf", PdfDocumentParser),
        (DOCX_CONTENT_TYPE, DocxDocumentParser),
    ],
)
def test_default_registry(content_type: str, parser_type: type) -> None:
    assert isinstance(create_default_parser_registry().get(content_type), parser_type)


@pytest.mark.parametrize("content_type", ["application/msword", "image/jpeg", "audio/mpeg"])
def test_default_registry_does_not_guess(content_type: str) -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        create_default_parser_registry().get(content_type)


def test_default_registry_parses_end_to_end() -> None:
    registry = create_default_parser_registry()
    content_type = "text/plain; charset=utf-8"

    document = registry.get(content_type).parse(b"Hello\r\nWorld", content_type=content_type)

    assert document.text == "Hello\nWorld"
