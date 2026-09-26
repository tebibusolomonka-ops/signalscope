"""A fake reranker for tests.

It scores a passage by how many times it contains the query words, so the
expected order is easy to work out. The scores carry no meaning.
"""

import re
from collections.abc import Sequence


class FakeReranker:
    def __init__(self, provider_name: str = "test", model_name: str = "word-count") -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.calls: list[tuple[str, list[str]]] = []
        self.error: Exception | None = None
        self.answer: list[float] | None = None

    def score_of(self, query: str, passage: str) -> float:
        words = set(re.findall(r"\w+", query.lower()))
        return float(sum(1 for word in re.findall(r"\w+", passage.lower()) if word in words))

    async def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.calls.append((query, list(passages)))
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer
        return [self.score_of(query, passage) for passage in passages]
