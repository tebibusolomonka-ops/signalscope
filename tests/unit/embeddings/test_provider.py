from collections.abc import Sequence

import pytest

from signalscope.core.errors import SignalScopeError
from signalscope.embeddings.provider import EmbeddingError, EmbeddingProvider, embed

pytestmark = pytest.mark.anyio


class FakeProvider:
    """A test provider. Its vectors mean nothing: they only count letters."""

    provider_name = "test"
    model_name = "letters-3"
    dimensions = 3

    def __init__(self, answer: list[list[float]] | None = None) -> None:
        self.answer = answer
        self.calls: list[list[str]] = []

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.answer is not None:
            return self.answer
        return [[float(len(text)), float(text.count("a")), 1.0] for text in texts]


def test_fake_provider_follows_the_protocol() -> None:
    provider: EmbeddingProvider = FakeProvider()

    assert (provider.provider_name, provider.model_name, provider.dimensions) == (
        "test",
        "letters-3",
        3,
    )


async def test_one_text() -> None:
    assert await embed(FakeProvider(), ["banana"]) == [[6.0, 3.0, 1.0]]


async def test_several_texts_in_one_call() -> None:
    provider = FakeProvider()

    vectors = await embed(provider, ["a", "bb", "ccc"])

    assert vectors == [[1.0, 1.0, 1.0], [2.0, 0.0, 1.0], [3.0, 0.0, 1.0]]
    assert provider.calls == [["a", "bb", "ccc"]]


async def test_no_texts_calls_nothing() -> None:
    provider = FakeProvider()

    assert await embed(provider, []) == []
    assert provider.calls == []


async def test_whole_numbers_become_floats() -> None:
    vectors = await embed(FakeProvider([[1, 2, 3]]), ["x"])  # type: ignore[list-item]

    assert vectors == [[1.0, 2.0, 3.0]]
    assert all(isinstance(value, float) for value in vectors[0])


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ([], "returned 0 vectors for 1 texts"),
        ([[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]], "returned 2 vectors for 1 texts"),
        ([[1.0, 2.0]], "2 dimensions instead of 3"),
        ([[1.0, 2.0, 3.0, 4.0]], "4 dimensions instead of 3"),
        ([[1.0, float("nan"), 3.0]], "not a number"),
        ([[1.0, float("inf"), 3.0]], "not a number"),
        ([[1.0, float("-inf"), 3.0]], "not a number"),
        ([["1", 2.0, 3.0]], "not a number"),
    ],
)
async def test_bad_answers_are_rejected(answer: list[list[float]], message: str) -> None:
    with pytest.raises(EmbeddingError, match=message) as error:
        await embed(FakeProvider(answer), ["x"])

    assert "test/letters-3" in str(error.value)


def test_embedding_error_is_safe_to_show() -> None:
    assert issubclass(EmbeddingError, SignalScopeError)
    assert str(EmbeddingError()) == "Embedding failed."
