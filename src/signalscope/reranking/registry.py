from signalscope.reranking.provider import RerankerProvider, RerankerUnavailableError


class DuplicateRerankerError(ValueError):
    pass


class RerankerRegistry:
    """The rerankers this process can use, by provider and model name.

    Rerankers are only added by explicit registration, so a new registry is
    empty.
    """

    def __init__(self) -> None:
        self._rerankers: dict[tuple[str, str], RerankerProvider] = {}

    def register(self, reranker: RerankerProvider) -> None:
        key = (reranker.provider_name, reranker.model_name)
        if key in self._rerankers:
            raise DuplicateRerankerError(f"Reranker {key[0]}/{key[1]} is already registered.")
        self._rerankers[key] = reranker

    def get(self, provider_name: str, model_name: str) -> RerankerProvider:
        reranker = self._rerankers.get((provider_name, model_name))
        if reranker is None:
            raise RerankerUnavailableError(
                f"Reranker {provider_name}/{model_name} is not configured."
            )
        return reranker

    def keys(self) -> list[tuple[str, str]]:
        """Return the (provider, model) pairs that are registered, sorted."""
        return sorted(self._rerankers)
