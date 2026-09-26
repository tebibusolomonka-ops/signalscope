from signalscope.ingestion.web_page import parse_web_page
from signalscope.parsing.content_type import content_charset
from signalscope.parsing.types import MetadataValue, ParsedDocument, single_section


class HtmlDocumentParser:
    """Reads text/html and application/xhtml+xml documents.

    The page is read the same way as during web ingestion, so both give the
    same text. Nothing is fetched and no scripts run.
    """

    def parse(
        self,
        data: bytes,
        *,
        content_type: str,
        filename: str | None = None,
        source_url: str | None = None,
    ) -> ParsedDocument:
        page = parse_web_page(_decode(data, content_charset(content_type)), source_url)
        metadata: dict[str, MetadataValue] = {}
        if page.canonical_url is not None:
            metadata["canonical_url"] = page.canonical_url
        if page.published_at is not None:
            metadata["published_at"] = page.published_at.isoformat()
        return ParsedDocument(
            text=page.text,
            title=page.title,
            language=page.language,
            metadata=metadata,
            sections=single_section(page.text, "body"),
        )


def _decode(data: bytes, charset: str | None) -> str | bytes:
    # A charset from the content type wins. Without one, or when it does not
    # fit the bytes, the page's own encoding declaration is used.
    if charset is not None:
        try:
            return data.decode(charset)
        except UnicodeDecodeError:
            pass
    return data
