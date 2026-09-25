from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from signalscope.domain.documents.language import normalize_language
from signalscope.domain.sources.model import Source


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestedItem:
    """One content item found by an adapter. The fields map onto Document."""

    external_id: str | None = None
    url: str | None = None
    title: str | None = None
    content: str | None = None
    language: str | None = None
    published_at: datetime | None = None

    def __post_init__(self) -> None:
        # The dataclass is frozen, so cleaned values are set with object.__setattr__.
        if self.url is not None:
            url = self.url.strip()
            if not url:
                raise ValueError("url must not be empty")
            object.__setattr__(self, "url", url)
        if self.language is not None:
            object.__setattr__(self, "language", normalize_language(self.language))
        if self.published_at is not None and self.published_at.utcoffset() is None:
            raise ValueError("published_at must include a timezone")


class IngestionAdapter(Protocol):
    """Reads content from one kind of source, such as an RSS feed or a web page.

    An async generator is enough to implement it:

        class FeedAdapter:
            async def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
                yield IngestedItem(title="...")
    """

    def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
        """Yield the items the source has now.

        Items come one at a time, so a large feed never has to fit in memory
        and the caller can stop early.
        """
        ...
