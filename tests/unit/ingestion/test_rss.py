from datetime import UTC, datetime

import httpx
import pytest

from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.errors import IngestionError
from signalscope.domain.sources.model import Source, SourceType
from signalscope.ingestion.http import HttpFetcher
from signalscope.ingestion.rss import RssIngestionAdapter, parse_feed
from signalscope.ingestion.text import html_to_text

FEED_URL = "https://news.example/feed.xml"

RSS = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Example news</title>
    <language>en-US</language>
    <item>
      <guid isPermaLink="false">item-1</guid>
      <link>https://news.example/articles/1</link>
      <title>First story</title>
      <description>
        &lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;.&lt;/p&gt;
        &lt;p&gt;Second line.&lt;/p&gt;
      </description>
      <pubDate>Sun, 01 Mar 2026 12:00:00 +0200</pubDate>
    </item>
    <item>
      <link>/articles/2</link>
      <title>Second story</title>
      <pubDate>not a real date</pubDate>
    </item>
    <item>
      <title>Only a title</title>
    </item>
  </channel>
</rss>
"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="de">
  <title>Beispiel</title>
  <id>urn:example:feed</id>
  <updated>2026-03-02T10:00:00Z</updated>
  <entry>
    <id>urn:example:entry:1</id>
    <title>Erster Eintrag</title>
    <link href="https://news.example/de/1"/>
    <updated>2026-03-02T10:00:00Z</updated>
    <summary>Kurz</summary>
    <content type="html">&lt;p&gt;Der ganze Text.&lt;/p&gt;</content>
  </entry>
</feed>
"""

EMPTY_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Nothing yet</title></channel></rss>
"""


def test_rss_items_are_mapped() -> None:
    first, second, third = parse_feed(RSS, FEED_URL)

    assert first == IngestedItem(
        external_id="item-1",
        url="https://news.example/articles/1",
        title="First story",
        content="Hello world.\nSecond line.",
        language="en-us",
        published_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
    )
    # Without a GUID the link is the identity. Relative links use the feed URL.
    assert second.external_id == "https://news.example/articles/2"
    assert second.url == "https://news.example/articles/2"
    assert second.published_at is None
    assert third == IngestedItem(title="Only a title", language="en-us")


def test_atom_entry_prefers_full_content() -> None:
    [entry] = parse_feed(ATOM, FEED_URL)

    assert entry == IngestedItem(
        external_id="urn:example:entry:1",
        url="https://news.example/de/1",
        title="Erster Eintrag",
        content="Der ganze Text.",
        language="de",
        published_at=datetime(2026, 3, 2, 10, 0, tzinfo=UTC),
    )


def test_empty_feed_has_no_items() -> None:
    assert list(parse_feed(EMPTY_RSS, FEED_URL)) == []


@pytest.mark.parametrize("body", [b"<html><body>Not a feed</body></html>", b"", b"plain text"])
def test_non_feed_is_an_error(body: bytes) -> None:
    with pytest.raises(IngestionError, match="not an RSS or Atom feed"):
        list(parse_feed(body, FEED_URL))


def test_html_to_text_keeps_paragraphs_and_drops_scripts() -> None:
    html = "<p>One <i>two</i></p><script>alert(1)</script><ul><li>A</li><li>B</li></ul>x<br>y"

    assert html_to_text(html) == "One two\nA\nB\nx\ny"


async def public_address(host: str) -> list[str]:
    return ["93.184.215.14"]


def adapter(handler: httpx.MockTransport) -> RssIngestionAdapter:
    return RssIngestionAdapter(HttpFetcher(transport=handler, resolve=public_address))


@pytest.mark.anyio
async def test_adapter_fetches_and_parses_the_feed() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, content=ATOM, headers={"Content-Type": "application/atom+xml"})

    source = Source(type=SourceType.RSS, name="Beispiel", url=FEED_URL)

    items = [item async for item in adapter(httpx.MockTransport(handler)).fetch(source)]

    assert requested == [FEED_URL]
    assert [item.title for item in items] == ["Erster Eintrag"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("source", "message"),
    [
        (Source(type=SourceType.WEB, name="Site", url=FEED_URL), "cannot read web sources"),
        (Source(type=SourceType.RSS, name="No URL", url=None), "Source has no URL."),
    ],
)
async def test_adapter_rejects_sources_it_cannot_read(source: Source, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("No request should be made.")

    with pytest.raises(IngestionError, match=message):
        async for _ in adapter(httpx.MockTransport(handler)).fetch(source):
            pass
