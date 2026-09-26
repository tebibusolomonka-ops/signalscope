from collections.abc import Sequence

import pytest

from signalscope.core.errors import ServiceUnavailableError
from signalscope.embeddings.registry import (
    DuplicateEmbeddingProviderError,
    EmbeddingProviderRegistry,
    EmbeddingProviderUnavailableError,
)


class FakeProvider:
    def __init__(self, provider_name: str = "test", model_name: str = "tiny-2") -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.dimensions = 2

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def test_a_new_registry_is_empty() -> None:
    assert EmbeddingProviderRegistry().keys() == []


def test_registered_provider_is_found() -> None:
    registry = EmbeddingProviderRegistry()
    provider = FakeProvider()

    registry.register(provider)

    assert registry.get("test", "tiny-2") is provider
    assert registry.keys() == [("test", "tiny-2")]


def test_several_models_of_one_provider() -> None:
    registry = EmbeddingProviderRegistry()
    small = FakeProvider(model_name="small")
    large = FakeProvider(model_name="large")

    registry.register(small)
    registry.register(large)

    assert registry.get("test", "small") is small
    assert registry.get("test", "large") is large
    assert registry.keys() == [("test", "large"), ("test", "small")]


def test_same_model_twice_is_rejected() -> None:
    registry = EmbeddingProviderRegistry()
    registry.register(FakeProvider())

    with pytest.raises(DuplicateEmbeddingProviderError, match="test/tiny-2 is already"):
        registry.register(FakeProvider())


@pytest.mark.parametrize(("provider_name", "model_name"), [("other", "tiny-2"), ("test", "other")])
def test_unknown_provider_or_model(provider_name: str, model_name: str) -> None:
    registry = EmbeddingProviderRegistry()
    registry.register(FakeProvider())

    with pytest.raises(EmbeddingProviderUnavailableError, match="is not configured") as error:
        registry.get(provider_name, model_name)

    assert f"{provider_name}/{model_name}" in str(error.value)
    assert isinstance(error.value, ServiceUnavailableError)
