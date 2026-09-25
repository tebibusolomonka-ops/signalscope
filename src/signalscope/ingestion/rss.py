import logging
from calendar import timegm
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

import feedparser

from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.errors import IngestionError
from signalscope.domain.sources.model import Source, SourceType
from signalscope.ingestion.http import HttpFetcher
from signalscope.ingestion.text import html_to_text

logger = logging.getLogger(__name__)


class RssIngestionAdapter:
    """Reads RSS and Atom feeds."""

    def __init__(self, fetcher: HttpFetcher) -> None:
        self.fetcher = fetcher

    async def fetch(self, source: Source) -> AsyncIterator[IngestedItem]:
        if source.type is not SourceType.RSS:
            raise IngestionError(f"The RSS adapter cannot read {source.type} sources.")
        if not source.url:
            raise IngestionError("Source has no URL.")
        response = await self.fetcher.get(source.url)
        for item in parse_feed(response.body, response.url, response.headers.get("content-type")):
            yield item


def parse_feed(body: bytes, url: str, content_type: str | None = None) -> Iterator[IngestedItem]:
    """Turn RSS or Atom XML into items. Entries that cannot be read are skipped."""
    headers = {"content-location": url}
    if content_type:
        headers["content-type"] = content_type
    # Given bytes, feedparser only parses. It never fetches anything itself.
    feed = feedparser.parse(body, response_headers=headers)
    if not feed.get("version") and not feed.entries:
        raise IngestionError("Response is not an RSS or Atom feed.")

    feed_language = _text(feed.feed.get("language"))
    for entry in feed.entries:
        try:
            item = _item(entry, feed_language)
        except ValueError as error:
            logger.warning("Skipped a feed entry from %s: %s", url, error)
            continue
        yield item


def _item(entry: Any, feed_language: str | None) -> IngestedItem:
    url = _text(entry.get("link"))
    return IngestedItem(
        # Feeds without an ID use the link as the entry's identity.
        external_id=_text(entry.get("id")) or url,
        url=url,
        title=_text(entry.get("title")),
        content=_content(entry),
        language=_language(entry) or feed_language,
        published_at=_published_at(entry),
    )


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _content(entry: Any) -> str | None:
    """The full content when the feed has it, otherwise the summary, as plain text."""
    for part in entry.get("content", []):
        text = html_to_text(part.get("value", ""))
        if text:
            return text
    summary = _text(entry.get("summary"))
    return html_to_text(summary) or None if summary else None


def _language(entry: Any) -> str | None:
    for detail in [*entry.get("content", []), entry.get("title_detail", {})]:
        language = _text(detail.get("language"))
        if language:
            return language
    return None


def _published_at(entry: Any) -> datetime | None:
    # Checking with "in" first avoids a feedparser warning when there is no updated date.
    for key in ("published_parsed", "updated_parsed"):
        if key in entry and entry[key]:
            return _date(entry[key])
    return None


def _date(value: Any) -> datetime | None:
    # feedparser gives dates as UTC time tuples.
    try:
        return datetime.fromtimestamp(timegm(value), tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None
