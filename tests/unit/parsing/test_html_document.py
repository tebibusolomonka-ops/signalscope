from signalscope.ingestion.web_page import parse_web_page
from signalscope.parsing.html_document import HtmlDocumentParser
from signalscope.parsing.types import ParsedDocument

PAGE = b"""<!DOCTYPE html>
<html lang="en-GB">
<head>
  <title>  Example   story </title>
  <link rel="canonical" href="/news/story">
  <meta property="article:published_time" content="2026-03-01T09:30:00+02:00">
  <style>p { color: red; }</style>
  <script>document.write("tracking");</script>
</head>
<body>
  <nav>Home</nav>
  <h1>Example story</h1>
  <p>First paragraph.</p>
  <p>Second paragraph.</p>
  <script>alert("never shown");</script>
  <img src="https://tracker.example/pixel.gif">
</body>
</html>
"""


def parse(
    data: bytes, content_type: str = "text/html", source_url: str | None = None
) -> ParsedDocument:
    return HtmlDocumentParser().parse(data, content_type=content_type, source_url=source_url)


def test_page_is_read_like_web_ingestion() -> None:
    document = parse(PAGE, source_url="https://news.example/latest")
    page = parse_web_page(PAGE, "https://news.example/latest")

    assert document.text == page.text
    assert document.title == "Example story"
    assert document.language == "en-gb"
    assert document.metadata == {
        "canonical_url": "https://news.example/news/story",
        "published_at": "2026-03-01T07:30:00+00:00",
    }


def test_scripts_and_styles_are_not_text() -> None:
    text = parse(PAGE).text

    assert "First paragraph." in text
    assert "Second paragraph." in text
    assert "tracking" not in text
    assert "never shown" not in text
    assert "color: red" not in text


def test_without_a_source_url_only_absolute_canonical_urls_are_kept() -> None:
    relative = b'<head><link rel="canonical" href="/news/story"></head><p>Hi</p>'
    absolute = b'<head><link rel="canonical" href="https://news.example/a"></head><p>Hi</p>'

    assert "canonical_url" not in parse(relative).metadata
    assert parse(absolute).metadata == {"canonical_url": "https://news.example/a"}


def test_page_without_extras() -> None:
    document = parse(b"<p>Just text</p>")

    assert document.text == "Just text"
    assert (document.title, document.language) == (None, None)
    assert document.metadata == {}


def test_empty_page_has_empty_text() -> None:
    assert parse(b"<html><head><title>Empty</title></head><body></body></html>").text == ""
    assert parse(b"").text == ""


def test_xhtml() -> None:
    xhtml = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="fr">
<head><title>Bonjour</title></head>
<body><p>Caf\xc3\xa9 cr\xc3\xa8me</p><br/></body>
</html>"""

    document = parse(xhtml, content_type="application/xhtml+xml")

    assert document.text == "Café crème"
    assert document.title == "Bonjour"
    assert document.language == "fr"


def test_charset_from_the_content_type_is_used() -> None:
    html = "<p>Привет</p>".encode("windows-1251")

    document = parse(html, content_type="text/html; charset=windows-1251")

    assert document.text == "Привет"


def test_encoding_declared_in_the_page_is_used() -> None:
    html = '<meta charset="iso-8859-1"><p>café</p>'.encode("iso-8859-1")

    assert parse(html).text == "café"


def test_wrong_charset_falls_back_to_the_page() -> None:
    html = '<meta charset="utf-8"><p>café</p>'.encode()

    assert parse(html, content_type="text/html; charset=ascii").text == "café"
