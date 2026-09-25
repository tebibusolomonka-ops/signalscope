from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from signalscope.core.errors import SignalScopeError

MetadataValue = str | int | float | bool


class DocumentParsingError(SignalScopeError):
    """A document could not be read. The message is safe to show to people."""

    default_message = "Document could not be parsed."


class UnsupportedDocumentTypeError(DocumentParsingError):
    default_message = "Document type is not supported."


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedDocument:
    """The text and basic facts taken out of one document.

    Empty text means the document had no text that could be read, such as a
    scanned PDF without a text layer.
    """

    text: str
    title: str | None = None
    language: str | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # A read-only copy, so neither the parser nor the caller can change it later.
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class DocumentParser(Protocol):
    """Reads one kind of document.

    content_type is the full media type, parameters included, so a parser can
    use a charset. Parsers never make network requests.
    """

    def parse(
        self,
        data: bytes,
        *,
        content_type: str,
        filename: str | None = None,
        source_url: str | None = None,
    ) -> ParsedDocument: ...
