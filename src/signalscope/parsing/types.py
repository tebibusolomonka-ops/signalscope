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


# Put between the texts of two sections in ParsedDocument.text.
SECTION_SEPARATOR = "\n\n"


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedSection:
    """One part of a document, such as a PDF page or the part under a heading.

    kind says what the part is, for example "page". index counts the sections
    of a document from 0.
    """

    text: str
    kind: str
    index: int
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedDocument:
    """The text and basic facts taken out of one document.

    Empty text means the document had no text that could be read, such as a
    scanned PDF without a text layer.

    sections splits the text into parts. When there are sections, text is
    exactly their texts joined by SECTION_SEPARATOR, so each section has a
    known place in text.
    """

    text: str
    title: str | None = None
    language: str | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)
    sections: tuple[ParsedSection, ...] = ()

    def __post_init__(self) -> None:
        # A read-only copy, so neither the parser nor the caller can change it later.
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(self, "sections", tuple(self.sections))
        if [section.index for section in self.sections] != list(range(len(self.sections))):
            raise ValueError("section indexes must count from 0 in order")
        if any(not section.text for section in self.sections):
            raise ValueError("sections must not be empty")
        if self.sections and SECTION_SEPARATOR.join(s.text for s in self.sections) != self.text:
            raise ValueError("text must be the section texts joined by SECTION_SEPARATOR")


def single_section(text: str, kind: str) -> tuple[ParsedSection, ...]:
    """The sections of a document that is one part: none for empty text."""
    return (ParsedSection(text=text, kind=kind, index=0),) if text else ()


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
