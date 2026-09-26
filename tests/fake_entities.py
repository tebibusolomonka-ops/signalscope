"""A fake entity extraction model for tests.

It marks every word from a fixed list as an entity of a fixed type. It knows
nothing about language.
"""

import asyncio
import re

from signalscope.entities.provider import ExtractedEntityMention

KNOWN = {"Merkel": "person", "Macron": "person", "Berlin": "location", "Siemens": "org"}


class FakeEntityExtractor:
    def __init__(
        self,
        provider_name: str = "test",
        model_name: str = "known-words",
        known: dict[str, str] | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.known = KNOWN if known is None else known
        self.calls: list[str] = []
        self.started = asyncio.Event()
        # When set, extract waits until the test sets this event.
        self.gate: asyncio.Event | None = None
        self.error: Exception | None = None
        self.answer: list[ExtractedEntityMention] | None = None

    async def extract(self, text: str) -> list[ExtractedEntityMention]:
        self.calls.append(text)
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer
        return [
            ExtractedEntityMention(
                text=match.group(),
                entity_type=self.known[match.group()],
                start_char=match.start(),
                end_char=match.end(),
                confidence=0.75,
            )
            for match in re.finditer(r"\w+", text)
            if match.group() in self.known
        ]
