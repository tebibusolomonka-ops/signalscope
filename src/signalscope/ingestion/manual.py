from collections.abc import AsyncGenerator, Iterable

from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.sources.model import Source


class ManualIngestionAdapter:
    """Yields items that were extracted elsewhere, such as from an upload.

    It reads nothing itself. The items are given when the adapter is created,
    so they go through the same ingestion steps as fetched content.
    """

    def __init__(self, items: Iterable[IngestedItem]) -> None:
        # A copy, so later changes to the caller's list do not change what is ingested.
        self._items = tuple(items)

    async def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
        for item in self._items:
            yield item
