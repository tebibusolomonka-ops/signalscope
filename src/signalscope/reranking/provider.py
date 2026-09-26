import math
from collections.abc import Sequence
from typing import Protocol

from signalscope.core.errors import ServiceUnavailableError


class RerankerUnavailableError(ServiceUnavailableError):
    default_message = "Reranker is not available."


class InvalidRerankerOutputError(ServiceUnavailableError):
    """The model answered, but not with one usable score per passage."""

    default_message = "Reranker returned invalid scores."


class RerankerProvider(Protocol):
    """Scores how well each passage answers a query, with one model.

    Higher scores mean more relevant. Scores are only comparable within one
    call to one model.
    """

    provider_name: str
    model_name: str

    async def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Return one score per passage, in the same order."""
        ...


async def rerank_scores(
    provider: RerankerProvider, query: str, passages: Sequence[str]
) -> list[float]:
    """Score passages with provider and check what comes back.

    Code should call this instead of provider.score, so every result is
    checked the same way.
    """
    if not passages:
        return []
    scores = await provider.score(query, list(passages))
    name = f"{provider.provider_name}/{provider.model_name}"
    if len(scores) != len(passages):
        raise InvalidRerankerOutputError(
            f"Reranker {name} returned {len(scores)} scores for {len(passages)} passages."
        )
    if not all(
        isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
        for value in scores
    ):
        raise InvalidRerankerOutputError(f"Reranker {name} returned a score that is not a number.")
    return [float(value) for value in scores]
