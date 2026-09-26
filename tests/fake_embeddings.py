"""A fake embedding provider for tests.

Its vectors only count a few fixed words, so they carry no meaning. They are
predictable, which lets tests know which chunk is closest to a query.
"""

import asyncio
import re
from collections.abc import Sequence

WORDS = ("climate", "energy", "water")


class FakeEmbeddingProvider:
    def __init__(
        self,
        provider_name: str = "test",
        model_name: str = "words-4",
        words: Sequence[str] = WORDS,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.words = tuple(words)
        # One number per word, plus a constant so no vector is all zeros.
        self.dimensions = len(self.words) + 1
        self.calls: list[list[str]] = []
        self.started = asyncio.Event()
        # When set, embed_texts waits until the test sets this event.
        self.gate: asyncio.Event | None = None
        self.error: Exception | None = None
        self.answer: list[list[float]] | None = None

    def vector(self, text: str) -> list[float]:
        tokens = re.findall(r"[a-z]+", text.lower())
        return [float(tokens.count(word)) for word in self.words] + [1.0]

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer
        return [self.vector(text) for text in texts]
