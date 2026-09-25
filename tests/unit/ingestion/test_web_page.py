from datetime import UTC, datetime

import pytest

from signalscope.ingestion.web_page import WebPage, parse_web_page

PAGE_URL = "https://news.example/articles/1?ref=feed"

PAGE = """<!doctype html>
<html lang="EN-GB">
<head>
  <title>
    A   long
    story
  </title>
  <link rel="canonical" href="/articles/1">
  <meta property="article:published_time" content="2026-03-01T12:00:00+02:00">
  <style>body { color: red }</style>
  <script>console.log("head")</script>
</head>
<body>
  <h1>A long story</h1>
  <p>First paragraph with <a href="/x">a link</a>.</p>
  <script>document.write("never shown")</script>
  <noscript>Enable JavaScript</noscript>
  <p>Second paragraph.</p>
</body>
</html>
"""


def test_page_fields_are_read() -> None:
    page = parse_web_page(PAGE, PAGE_URL)

    assert page == WebPage(
        title="A long story",
        text="A long story\nFirst paragraph with a link.\nSecond paragraph.",
        language="en-gb",
        canonical_url="https://news.example/articles/1",
        published_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
    )


def test_page_without_metadata() -> None:
    page = parse_web_page("<p>Just text</p>", PAGE_URL)

    assert page == WebPage(
        title=None, text="Just text", language=None, canonical_url=None, published_at=None
    )


def test_broken_html_is_still_read() -> None:
    page = parse_web_page("<html><body><p>One<p>Two</div></span><li>Three", PAGE_URL)

    assert page.text.splitlines() == ["One", "Two", "Three"]


def test_encoding_comes_from_the_page() -> None:
    html = '<meta charset="iso-8859-1"><title>Caf\xe9</title>'.encode("iso-8859-1")

    assert parse_web_page(html, PAGE_URL).title == "Café"


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ('<link rel="canonical" href="https://other.example/a">', "https://other.example/a"),
        ('<link rel="canonical alternate" href="page">', "https://news.example/articles/page"),
        ('<link rel="canonical" href="javascript:alert(1)">', None),
        ('<link rel="canonical" href="  ">', None),
        ('<link rel="stylesheet" href="/style.css">', None),
    ],
)
def test_canonical_url(link: str, expected: str | None) -> None:
    assert parse_web_page(f"<head>{link}</head>", PAGE_URL).canonical_url == expected


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        (
            '<meta itemprop="datePublished" content="2026-03-01T10:00:00Z">',
            datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
        ),
        (
            '<meta property="article:published_time" content="2026-03-01T10:00:00">',
            datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
        ),
        ('<meta property="article:published_time" content="yesterday">', None),
        ('<meta property="og:title" content="2026-03-01T10:00:00Z">', None),
    ],
)
def test_published_time(meta: str, expected: datetime | None) -> None:
    assert parse_web_page(f"<head>{meta}</head>", PAGE_URL).published_at == expected


@pytest.mark.parametrize("html", ['<html lang="">', '<html lang="  ">', "<html>"])
def test_missing_language(html: str) -> None:
    assert parse_web_page(html, PAGE_URL).language is None


@pytest.mark.parametrize(
    ("html", "text"),
    [
        ("<title>Only a title</title>", ""),
        ("<title>Title</title><p>Body text</p>", "Body text"),
        ("<head><title>Title</title><meta charset='utf-8'></head><p>Body text</p>", "Body text"),
    ],
)
def test_title_is_not_part_of_the_text(html: str, text: str) -> None:
    page = parse_web_page(html, PAGE_URL)

    assert page.text == text
    assert page.title is not None
