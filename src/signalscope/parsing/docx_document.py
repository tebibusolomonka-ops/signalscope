import io
import zipfile
from collections.abc import Iterator

import docx
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from signalscope.parsing.types import DocumentParsingError, MetadataValue, ParsedDocument

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_DOCX_BYTES = 50 * 1024 * 1024
# A DOCX file is a zip archive. This limits what it may unpack to, so a small
# file cannot expand into gigabytes.
MAX_UNPACKED_BYTES = 200 * 1024 * 1024


class DocxDocumentParser:
    """Reads the text of Word .docx documents.

    Paragraphs and table cells are read in document order, with a blank line
    between them. Images, embedded objects and macros are ignored.
    """

    def parse(
        self,
        data: bytes,
        *,
        content_type: str,
        filename: str | None = None,
        source_url: str | None = None,
    ) -> ParsedDocument:
        if len(data) > MAX_DOCX_BYTES:
            raise DocumentParsingError(
                f"DOCX file is larger than {MAX_DOCX_BYTES // (1024 * 1024)} MB."
            )
        _check_unpacked_size(data)
        try:
            document = docx.Document(io.BytesIO(data))
            blocks = [text for text in _container_texts(document) if text.strip()]
            properties = document.core_properties
            title, author = _clean(properties.title), _clean(properties.author)
        except Exception as error:
            # python-docx raises many kinds of errors for broken files. None are safe to show.
            raise DocumentParsingError("Document is not a readable DOCX file.") from error

        metadata: dict[str, MetadataValue] = {}
        if author is not None:
            metadata["author"] = author
        return ParsedDocument(text="\n\n".join(blocks), title=title, metadata=metadata)


def _check_unpacked_size(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            unpacked = sum(member.file_size for member in archive.infolist())
    except zipfile.BadZipFile as error:
        raise DocumentParsingError("Document is not a readable DOCX file.") from error
    if unpacked > MAX_UNPACKED_BYTES:
        raise DocumentParsingError("DOCX file unpacks to too much data.")


def _container_texts(container: docx.document.Document | _Cell) -> Iterator[str]:
    for block in container.iter_inner_content():
        if isinstance(block, Paragraph):
            yield block.text
        else:
            yield from _table_texts(block)


def _table_texts(table: Table) -> Iterator[str]:
    # A merged cell shows up once for every grid position it covers. python-docx
    # has no public way to tell, so the underlying XML elements are compared.
    # Keeping them in the set also keeps lxml from handing out new objects for them.
    seen: set[object] = set()
    for row in table.rows:
        for cell in row.cells:
            if cell._tc in seen:
                continue
            seen.add(cell._tc)
            # Cells can hold paragraphs and even other tables.
            yield from _container_texts(cell)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()) or None
