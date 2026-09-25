from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.errors import IngestionError
from signalscope.domain.sources.model import Source, SourceType
from signalscope.ingestion.http import HttpFetcher
from signalscope.ingestion.web import WebIngestionAdapter

pytestmark = pytest.mark.anyio

PAGE_URL = "https://news.example/story"
HTML = {"Content-Type": "text/html; charset=utf-8"}

PAGE = b"""<html lang="en"><head><title>Big story</title>
<meta property="article:published_time" content="2026-03-01T10:00:00Z"></head>
<body><p>The whole story.</p></body></html>"""


async def public_address(host: str) -> list[str]:
    return ["93.184.215.14"]


async def fetch_items(
    handler: Callable[[httpx.Request], httpx.Response], source: Source
) -> list[IngestedItem]:
    fetcher = HttpFetcher(transport=httpx.MockTransport(handler), resolve=public_address)
    async with fetcher:
        return [item async for item in WebIngestionAdapter(fetcher).fetch(source)]


def web_source(url: str | None = PAGE_URL) -> Source:
    return Source(type=SourceType.WEB, name="Example site", url=url)


async def test_page_becomes_one_item() -> None:
    items = await fetch_items(
        lambda request: httpx.Response(200, content=PAGE, headers=HTML), web_source()
    )

    assert items == [
        IngestedItem(
            external_id=PAGE_URL,
            url=PAGE_URL,
            title="Big story",
            content="The whole story.",
            language="en",
            published_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
        )
    ]


async def test_final_url_is_used_after_a_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/story":
            return httpx.Response(301, headers={"Location": "/2026/story"})
        return httpx.Response(200, content=PAGE, headers=HTML)

    [item] = await fetch_items(handler, web_source())

    assert item.url == "https://news.example/2026/story"
    assert item.external_id == "https://news.example/2026/story"


async def test_canonical_url_is_preferred() -> None:
    page = b'<head><link rel="canonical" href="https://news.example/canonical"></head><p>Hi</p>'

    [item] = await fetch_items(
        lambda request: httpx.Response(200, content=page, headers=HTML),
        web_source(PAGE_URL + "?utm_source=feed"),
    )

    assert item.url == "https://news.example/canonical"
    assert item.external_id == "https://news.example/canonical"


async def test_xhtml_is_accepted() -> None:
    headers = {"Content-Type": "application/xhtml+xml"}

    [item] = await fetch_items(
        lambda request: httpx.Response(200, content=PAGE, headers=headers), web_source()
    )

    assert item.title == "Big story"


async def test_page_without_text_has_no_content() -> None:
    [item] = await fetch_items(
        lambda request: httpx.Response(200, content=b"<title>Empty</title>", headers=HTML),
        web_source(),
    )

    assert item.content is None


@pytest.mark.parametrize(
    ("headers", "received"),
    [({"Content-Type": "image/png"}, "image/png"), ({}, "no content type")],
)
async def test_other_content_types_are_rejected(headers: dict[str, str], received: str) -> None:
    with pytest.raises(IngestionError, match=f"Expected an HTML page, got {received}."):
        await fetch_items(
            lambda request: httpx.Response(200, content=b"\x89PNG", headers=headers),
            web_source(),
        )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (Source(type=SourceType.RSS, name="Feed", url=PAGE_URL), "cannot read rss sources"),
        (web_source(url=None), "Source has no URL."),
    ],
)
async def test_sources_it_cannot_read_are_rejected(source: Source, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("No request should be made.")

    with pytest.raises(IngestionError, match=message):
        await fetch_items(handler, source)
