import dataclasses
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest

from signalscope.domain.ingestion.adapter import IngestedItem, IngestionAdapter
from signalscope.domain.sources.model import Source, SourceType

SOURCE = Source(type=SourceType.RSS, name="Example feed", url="https://example.com/rss")


class ListAdapter:
    """A fake adapter that yields fixed items and counts how many it produced."""

    def __init__(self, items: list[IngestedItem]) -> None:
        self.items = items
        self.produced = 0

    async def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
        for item in self.items:
            self.produced += 1
            yield item


async def collect(adapter: IngestionAdapter, source: Source, limit: int) -> list[IngestedItem]:
    items: list[IngestedItem] = []
    async for item in adapter.fetch(source):
        items.append(item)
        if len(items) == limit:
            break
    return items


def test_item_fields_are_optional() -> None:
    item = IngestedItem()

    assert (
        item.external_id,
        item.url,
        item.title,
        item.content,
        item.language,
        item.published_at,
    ) == (
        None,
        None,
        None,
        None,
        None,
        None,
    )


def test_item_cannot_be_changed() -> None:
    item = IngestedItem(title="An article")

    with pytest.raises(dataclasses.FrozenInstanceError):
        item.title = "Another title"  # type: ignore[misc]


def test_item_needs_timezone_aware_published_at() -> None:
    IngestedItem(published_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC))

    with pytest.raises(ValueError, match="published_at must include a timezone"):
        IngestedItem(published_at=datetime(2026, 3, 1, 10, 0))


@pytest.mark.anyio
async def test_adapter_items_arrive_in_order() -> None:
    items = [IngestedItem(external_id=f"guid-{number}") for number in range(3)]
    adapter = ListAdapter(items)

    assert await collect(adapter, SOURCE, limit=10) == items


@pytest.mark.anyio
async def test_caller_can_stop_early() -> None:
    adapter = ListAdapter([IngestedItem(external_id=f"guid-{number}") for number in range(100)])

    items = await collect(adapter, SOURCE, limit=2)

    assert [item.external_id for item in items] == ["guid-0", "guid-1"]
    assert adapter.produced == 2


def test_item_language_is_normalized() -> None:
    assert IngestedItem(language=" EN-GB ").language == "en-gb"
    assert IngestedItem(language=None).language is None


def test_item_rejects_blank_language() -> None:
    with pytest.raises(ValueError, match="language must not be empty"):
        IngestedItem(language="  ")


def test_item_url_is_trimmed() -> None:
    assert IngestedItem(url=" https://example.com/a ").url == "https://example.com/a"
    assert IngestedItem().url is None


def test_item_rejects_blank_url() -> None:
    with pytest.raises(ValueError, match="url must not be empty"):
        IngestedItem(url="   ")
