from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from signalscope.domain.documents.language import normalize_language
from signalscope.domain.sources.model import Source


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestedItem:
    """One content item found by an adapter. The fields map onto Document."""

    external_id: str | None = None
    title: str | None = None
    content: str | None = None
    language: str | None = None
    published_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.language is not None:
            # The dataclass is frozen, so the normalized value is set this way.
            object.__setattr__(self, "language", normalize_language(self.language))
        if self.published_at is not None and self.published_at.utcoffset() is None:
            raise ValueError("published_at must include a timezone")


class IngestionAdapter(Protocol):
    """Reads content from one kind of source, such as an RSS feed or a web page.

    An async generator is enough to implement it:

        class FeedAdapter:
            async def fetch(self, source: Source) -> AsyncIterator[IngestedItem]:
                yield IngestedItem(title="...")
    """

    def fetch(self, source: Source) -> AsyncIterator[IngestedItem]:
        """Yield the items the source has now.

        Items come one at a time, so a large feed never has to fit in memory
        and the caller can stop early.
        """
        ...
