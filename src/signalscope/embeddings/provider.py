import math
from collections.abc import Sequence
from typing import Protocol

from signalscope.core.errors import SignalScopeError


class EmbeddingError(SignalScopeError):
    """An embedding could not be made. The message is safe to store and show."""

    default_message = "Embedding failed."


class EmbeddingProvider(Protocol):
    """Makes vectors from texts with one model.

    provider_name says who runs the model, such as "local", and model_name
    which model it is. Every vector has dimensions numbers.
    """

    provider_name: str
    model_name: str
    dimensions: int

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per text, in the same order."""
        ...


async def embed(provider: EmbeddingProvider, texts: Sequence[str]) -> list[list[float]]:
    """Embed texts with provider and check what comes back.

    Code should call this instead of provider.embed_texts, so every vector is
    checked the same way before it is stored or searched with.
    """
    if not texts:
        return []
    vectors = await provider.embed_texts(list(texts))
    check_vectors(provider, vectors, expected_count=len(texts))
    return [[float(value) for value in vector] for vector in vectors]


def check_vectors(
    provider: EmbeddingProvider, vectors: Sequence[Sequence[float]], expected_count: int
) -> None:
    name = f"{provider.provider_name}/{provider.model_name}"
    if len(vectors) != expected_count:
        raise EmbeddingError(
            f"Embedding model {name} returned {len(vectors)} vectors for {expected_count} texts."
        )
    for vector in vectors:
        if len(vector) != provider.dimensions:
            raise EmbeddingError(
                f"Embedding model {name} returned a vector with {len(vector)} "
                f"dimensions instead of {provider.dimensions}."
            )
        if not all(isinstance(value, int | float) and math.isfinite(value) for value in vector):
            raise EmbeddingError(f"Embedding model {name} returned a value that is not a number.")
