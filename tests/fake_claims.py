"""A fake claim extraction model for tests.

Every sentence with a number in it counts as a "statistic" claim. It knows
nothing about language.
"""

import asyncio
import re

from signalscope.claims.provider import ExtractedClaim


class FakeClaimExtractor:
    def __init__(self, provider_name: str = "test", model_name: str = "number-sentences") -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.calls: list[str] = []
        self.started = asyncio.Event()
        # When set, extract waits until the test sets this event.
        self.gate: asyncio.Event | None = None
        self.error: Exception | None = None
        self.answer: list[ExtractedClaim] | None = None

    async def extract(self, text: str) -> list[ExtractedClaim]:
        self.calls.append(text)
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer
        return [
            ExtractedClaim(
                text=match.group().rstrip("."),
                claim_type="statistic",
                surface_text=match.group(),
                start_char=match.start(),
                end_char=match.end(),
                confidence=0.8,
            )
            for match in re.finditer(r"[^.]*\d[^.]*\.", text)
        ]
