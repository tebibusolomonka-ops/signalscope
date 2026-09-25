from signalscope.parsing.content_type import media_type
from signalscope.parsing.docx_document import DOCX_CONTENT_TYPE, DocxDocumentParser
from signalscope.parsing.html_document import HtmlDocumentParser
from signalscope.parsing.json_document import JsonParser
from signalscope.parsing.pdf_document import PdfDocumentParser
from signalscope.parsing.plain_text import PlainTextParser
from signalscope.parsing.types import DocumentParser, UnsupportedDocumentTypeError

# Longer values are cut in error messages.
MAX_SHOWN_CONTENT_TYPE_LENGTH = 100


class ParserRegistry:
    """Finds the parser for a document's content type.

    Content types are compared without parameters and case, so
    "Text/Plain; charset=utf-8" finds the text/plain parser.
    """

    def __init__(self) -> None:
        self._parsers: dict[str, DocumentParser] = {}

    def register(self, content_type: str, parser: DocumentParser) -> None:
        key = media_type(content_type)
        if not key:
            raise ValueError("content type must not be empty")
        if key in self._parsers:
            raise ValueError(f"A parser is already registered for {key}.")
        self._parsers[key] = parser

    def get(self, content_type: str) -> DocumentParser:
        key = media_type(content_type)
        parser = self._parsers.get(key)
        if parser is None:
            shown = key[:MAX_SHOWN_CONTENT_TYPE_LENGTH] or "an empty content type"
            raise UnsupportedDocumentTypeError(f"No parser is available for {shown}.")
        return parser


def create_default_parser_registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register("text/plain", PlainTextParser())
    registry.register("application/json", JsonParser())
    html = HtmlDocumentParser()
    registry.register("text/html", html)
    registry.register("application/xhtml+xml", html)
    registry.register("application/pdf", PdfDocumentParser())
    registry.register(DOCX_CONTENT_TYPE, DocxDocumentParser())
    return registry
