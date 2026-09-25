from signalscope.domain.ingestion.adapter import IngestionAdapter
from signalscope.domain.ingestion.errors import IngestionError
from signalscope.domain.sources.model import SourceType


class UnsupportedSourceTypeError(IngestionError):
    default_message = "No ingestion adapter is available for this source type."


class AdapterRegistry:
    """Picks the adapter that reads a given type of source.

    Adapters are registered one by one by the code that sets up ingestion.
    """

    def __init__(self) -> None:
        self._adapters: dict[SourceType, IngestionAdapter] = {}

    def register(self, source_type: SourceType, adapter: IngestionAdapter) -> None:
        # Replacing an adapter by accident would be hard to notice, so it is not allowed.
        if source_type in self._adapters:
            raise ValueError(f"An adapter is already registered for {source_type} sources.")
        self._adapters[source_type] = adapter

    def get(self, source_type: SourceType) -> IngestionAdapter:
        adapter = self._adapters.get(source_type)
        if adapter is None:
            raise UnsupportedSourceTypeError(
                f"No ingestion adapter is available for {source_type} sources."
            )
        return adapter
