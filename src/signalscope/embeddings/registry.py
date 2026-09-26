from signalscope.core.errors import ServiceUnavailableError
from signalscope.embeddings.provider import EmbeddingProvider

ModelKey = tuple[str, str]


class EmbeddingProviderUnavailableError(ServiceUnavailableError):
    default_message = "Embedding model is not available."


class DuplicateEmbeddingProviderError(ValueError):
    pass


class EmbeddingProviderRegistry:
    """The embedding models this process can use, by provider and model name.

    Providers are only added by explicit registration. SignalScope does not
    register any provider on its own yet, so a new registry is empty.
    """

    def __init__(self) -> None:
        self._providers: dict[ModelKey, EmbeddingProvider] = {}

    def register(self, provider: EmbeddingProvider) -> None:
        key = (provider.provider_name, provider.model_name)
        if key in self._providers:
            raise DuplicateEmbeddingProviderError(
                f"Embedding model {key[0]}/{key[1]} is already registered."
            )
        self._providers[key] = provider

    def get(self, provider_name: str, model_name: str) -> EmbeddingProvider:
        provider = self._providers.get((provider_name, model_name))
        if provider is None:
            raise EmbeddingProviderUnavailableError(
                f"Embedding model {provider_name}/{model_name} is not configured."
            )
        return provider

    def keys(self) -> list[ModelKey]:
        """Return the (provider, model) pairs that are registered, sorted."""
        return sorted(self._providers)
