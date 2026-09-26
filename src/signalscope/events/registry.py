from signalscope.events.provider import EventExtractionProvider, EventExtractorUnavailableError


class DuplicateEventExtractorError(ValueError):
    pass


class EventExtractorRegistry:
    """The event extraction models this process can use, by provider and model name.

    Models are only added by explicit registration. SignalScope has no event
    model yet, so a new registry is empty.
    """

    def __init__(self) -> None:
        self._providers: dict[tuple[str, str], EventExtractionProvider] = {}

    def register(self, provider: EventExtractionProvider) -> None:
        key = (provider.provider_name, provider.model_name)
        if key in self._providers:
            raise DuplicateEventExtractorError(
                f"Event extraction model {key[0]}/{key[1]} is already registered."
            )
        self._providers[key] = provider

    def get(self, provider_name: str, model_name: str) -> EventExtractionProvider:
        provider = self._providers.get((provider_name, model_name))
        if provider is None:
            raise EventExtractorUnavailableError(
                f"Event extraction model {provider_name}/{model_name} is not configured."
            )
        return provider

    def keys(self) -> list[tuple[str, str]]:
        """Return the (provider, model) pairs that are registered, sorted."""
        return sorted(self._providers)
