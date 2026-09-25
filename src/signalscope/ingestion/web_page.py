from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from signalscope.domain.documents.language import normalize_language
from signalscope.ingestion.text import element_text

PUBLISHED_TIME_META = [("property", "article:published_time"), ("itemprop", "datePublished")]


@dataclass(frozen=True, slots=True)
class WebPage:
    title: str | None
    text: str
    language: str | None
    canonical_url: str | None
    published_at: datetime | None


def parse_web_page(html: str | bytes, url: str) -> WebPage:
    """Read the parts of an HTML page that ingestion needs.

    Parsing never runs scripts or loads anything. With bytes, the encoding
    comes from the page itself.
    """
    soup = BeautifulSoup(html, "html.parser")
    return WebPage(
        title=_title(soup),
        language=_language(soup),
        canonical_url=_canonical_url(soup, url),
        published_at=_published_at(soup),
        # Last, because reading the text removes scripts and styles from the tree.
        text=element_text(soup.body or soup),
    )


def _title(soup: BeautifulSoup) -> str | None:
    if soup.title is None:
        return None
    return " ".join(soup.title.get_text().split()) or None


def _language(soup: BeautifulSoup) -> str | None:
    value = soup.html.get("lang") if soup.html is not None else None
    if not isinstance(value, str) or not value.strip():
        return None
    return normalize_language(value)


def _canonical_url(soup: BeautifulSoup, page_url: str) -> str | None:
    link = soup.find("link", rel="canonical")
    href = link.get("href") if isinstance(link, Tag) else None
    if not isinstance(href, str) or not href.strip():
        return None
    canonical = urljoin(page_url, href.strip())
    return canonical if urlsplit(canonical).scheme in ("http", "https") else None


def _published_at(soup: BeautifulSoup) -> datetime | None:
    for attribute, value in PUBLISHED_TIME_META:
        meta = soup.find("meta", attrs={attribute: value})
        content = meta.get("content") if isinstance(meta, Tag) else None
        if isinstance(content, str):
            try:
                published = datetime.fromisoformat(content.strip())
            except ValueError:
                continue
            # A time without an offset is read as UTC.
            if published.utcoffset() is None:
                published = published.replace(tzinfo=UTC)
            return published.astimezone(UTC)
    return None
