import dataclasses

import pytest

from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.sources.model import Source, SourceType
from signalscope.ingestion.manual import ManualIngestionAdapter

pytestmark = pytest.mark.anyio

SOURCE = Source(type=SourceType.UPLOAD, name="Uploads")


async def fetch_all(adapter: ManualIngestionAdapter) -> list[IngestedItem]:
    return [item async for item in adapter.fetch(SOURCE)]


async def test_one_item() -> None:
    item = IngestedItem(title="Report", content="Text from an upload.")

    assert await fetch_all(ManualIngestionAdapter([item])) == [item]


async def test_items_keep_their_order() -> None:
    items = [IngestedItem(external_id=f"file-{number}") for number in range(5)]

    assert await fetch_all(ManualIngestionAdapter(items)) == items


async def test_no_items() -> None:
    assert await fetch_all(ManualIngestionAdapter([])) == []


async def test_caller_can_stop_early() -> None:
    adapter = ManualIngestionAdapter(IngestedItem(external_id=f"file-{n}") for n in range(10))

    seen: list[IngestedItem] = []
    async for item in adapter.fetch(SOURCE):
        seen.append(item)
        if len(seen) == 2:
            break

    assert [item.external_id for item in seen] == ["file-0", "file-1"]
    # Stopping early does not use up the items for the next fetch.
    assert len(await fetch_all(adapter)) == 10


async def test_changing_the_input_list_later_has_no_effect() -> None:
    items = [IngestedItem(title="First")]
    adapter = ManualIngestionAdapter(items)

    items.append(IngestedItem(title="Added later"))
    items[0] = IngestedItem(title="Replaced")

    assert await fetch_all(adapter) == [IngestedItem(title="First")]


async def test_items_are_not_changed() -> None:
    item = IngestedItem(title="Report", language="EN")
    [fetched] = await fetch_all(ManualIngestionAdapter([item]))

    assert fetched is item
    with pytest.raises(dataclasses.FrozenInstanceError):
        fetched.title = "Changed"  # type: ignore[misc]
