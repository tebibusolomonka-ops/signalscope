from collections.abc import AsyncGenerator

import pytest

from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.errors import IngestionError
from signalscope.domain.ingestion.registry import AdapterRegistry, UnsupportedSourceTypeError
from signalscope.domain.sources.model import Source, SourceType


class EmptyAdapter:
    async def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
        items: list[IngestedItem] = []
        for item in items:
            yield item


def test_registered_adapter_is_returned_for_its_type() -> None:
    rss_adapter = EmptyAdapter()
    web_adapter = EmptyAdapter()
    registry = AdapterRegistry()

    registry.register(SourceType.RSS, rss_adapter)
    registry.register(SourceType.WEB, web_adapter)

    assert registry.get(SourceType.RSS) is rss_adapter
    assert registry.get(SourceType.WEB) is web_adapter


def test_registering_a_type_twice_is_rejected() -> None:
    registry = AdapterRegistry()
    registry.register(SourceType.RSS, EmptyAdapter())

    with pytest.raises(ValueError, match="already registered for rss sources"):
        registry.register(SourceType.RSS, EmptyAdapter())


def test_unsupported_type_raises_a_clear_error() -> None:
    registry = AdapterRegistry()
    registry.register(SourceType.RSS, EmptyAdapter())

    with pytest.raises(UnsupportedSourceTypeError) as error:
        registry.get(SourceType.API)

    assert str(error.value) == "No ingestion adapter is available for api sources."
    assert isinstance(error.value, IngestionError)
