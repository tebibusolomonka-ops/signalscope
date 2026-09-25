from collections.abc import AsyncGenerator

from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.errors import IngestionError
from signalscope.domain.sources.model import Source, SourceType
from signalscope.ingestion.http import HttpFetcher
from signalscope.ingestion.web_page import parse_web_page

HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})


class WebIngestionAdapter:
    """Reads one web page each time the source is fetched."""

    def __init__(self, fetcher: HttpFetcher) -> None:
        self.fetcher = fetcher

    async def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
        if source.type is not SourceType.WEB:
            raise IngestionError(f"The web adapter cannot read {source.type} sources.")
        if not source.url:
            raise IngestionError("Source has no URL.")

        response = await self.fetcher.get(source.url)
        if response.content_type not in HTML_CONTENT_TYPES:
            received = response.content_type or "no content type"
            raise IngestionError(f"Expected an HTML page, got {received}.")

        page = parse_web_page(response.body, response.url)
        # The canonical URL names the page itself, so it stays the same when the
        # fetched address has extra parameters or went through redirects.
        url = page.canonical_url or response.url
        yield IngestedItem(
            external_id=url,
            url=url,
            title=page.title,
            content=page.text or None,
            language=page.language,
            published_at=page.published_at,
        )
