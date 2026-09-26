from signalscope.claims.provider import ClaimExtractionProvider, ClaimExtractorUnavailableError


class DuplicateClaimExtractorError(ValueError):
    pass


class ClaimExtractorRegistry:
    """The claim extraction models this process can use, by provider and model name.

    Models are only added by explicit registration. SignalScope has no claim
    model yet, so a new registry is empty.
    """

    def __init__(self) -> None:
        self._providers: dict[tuple[str, str], ClaimExtractionProvider] = {}

    def register(self, provider: ClaimExtractionProvider) -> None:
        key = (provider.provider_name, provider.model_name)
        if key in self._providers:
            raise DuplicateClaimExtractorError(
                f"Claim extraction model {key[0]}/{key[1]} is already registered."
            )
        self._providers[key] = provider

    def get(self, provider_name: str, model_name: str) -> ClaimExtractionProvider:
        provider = self._providers.get((provider_name, model_name))
        if provider is None:
            raise ClaimExtractorUnavailableError(
                f"Claim extraction model {provider_name}/{model_name} is not configured."
            )
        return provider

    def keys(self) -> list[tuple[str, str]]:
        """Return the (provider, model) pairs that are registered, sorted."""
        return sorted(self._providers)
