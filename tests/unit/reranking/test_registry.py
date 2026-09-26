import pytest

from fake_reranker import FakeReranker
from signalscope.reranking.provider import RerankerUnavailableError
from signalscope.reranking.registry import DuplicateRerankerError, RerankerRegistry


def test_a_new_registry_is_empty() -> None:
    assert RerankerRegistry().keys() == []


def test_registered_reranker_is_found() -> None:
    registry = RerankerRegistry()
    reranker = FakeReranker()

    registry.register(reranker)

    assert registry.get("test", "word-count") is reranker
    assert registry.keys() == [("test", "word-count")]


def test_several_models() -> None:
    registry = RerankerRegistry()
    small, large = FakeReranker(model_name="small"), FakeReranker(model_name="large")

    registry.register(small)
    registry.register(large)

    assert registry.get("test", "small") is small
    assert registry.get("test", "large") is large
    assert registry.keys() == [("test", "large"), ("test", "small")]


def test_same_model_twice_is_rejected() -> None:
    registry = RerankerRegistry()
    registry.register(FakeReranker())

    with pytest.raises(DuplicateRerankerError, match="test/word-count is already"):
        registry.register(FakeReranker())


@pytest.mark.parametrize(("provider", "model"), [("other", "word-count"), ("test", "other")])
def test_missing_reranker(provider: str, model: str) -> None:
    registry = RerankerRegistry()
    registry.register(FakeReranker())

    with pytest.raises(RerankerUnavailableError, match=f"{provider}/{model} is not configured"):
        registry.get(provider, model)
