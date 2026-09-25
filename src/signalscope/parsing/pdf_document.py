import io
import logging

from pypdf import PageObject, PdfReader

from signalscope.parsing.types import DocumentParsingError, MetadataValue, ParsedDocument

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 50 * 1024 * 1024
# Pages after this are not read, and metadata["truncated"] is True.
MAX_PAGES = 2000


class PdfDocumentParser:
    """Reads the text layer of application/pdf documents.

    Page texts are joined in order with a blank line between pages. There is
    no OCR, so a scanned PDF without a text layer gives empty text. The title
    only comes from the PDF's own metadata.
    """

    def parse(
        self,
        data: bytes,
        *,
        content_type: str,
        filename: str | None = None,
        source_url: str | None = None,
    ) -> ParsedDocument:
        if len(data) > MAX_PDF_BYTES:
            raise DocumentParsingError(f"PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB.")
        reader = _open(data)
        if reader.is_encrypted:
            raise DocumentParsingError("PDF is encrypted.")
        try:
            pages = reader.pages
            page_count = len(pages)
            texts = [
                _page_text(pages[number], number) for number in range(min(page_count, MAX_PAGES))
            ]
            info = reader.metadata
        except Exception as error:
            raise DocumentParsingError("Document is not a readable PDF.") from error

        text = "\n\n".join(page_text for page_text in texts if page_text)
        # Without letters or digits, what came out is not text worth keeping.
        if not any(character.isalnum() for character in text):
            text = ""
        metadata: dict[str, MetadataValue] = {
            "page_count": page_count,
            "truncated": page_count > MAX_PAGES,
        }
        author = _clean(info.author if info is not None else None)
        if author is not None:
            metadata["author"] = author
        title = _clean(info.title if info is not None else None)
        return ParsedDocument(text=text, title=title, metadata=metadata)


def _open(data: bytes) -> PdfReader:
    try:
        return PdfReader(io.BytesIO(data))
    except Exception as error:
        # pypdf raises many kinds of errors for broken files. None of them are safe to show.
        raise DocumentParsingError("Document is not a readable PDF.") from error


def _page_text(page: PageObject, number: int) -> str:
    try:
        return page.extract_text().strip()
    except Exception:
        # One broken page should not hide the text of the others.
        logger.warning("Could not read the text of PDF page %s", number + 1, exc_info=True)
        return ""


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()) or None
