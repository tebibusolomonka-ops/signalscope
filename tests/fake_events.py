"""A fake event extraction model for tests.

It reports one "flood" event for every sentence that contains the word
"flood". It knows nothing about language.
"""

import asyncio
import re

from signalscope.events.provider import ExtractedEvent


class FakeEventExtractor:
    def __init__(self, provider_name: str = "test", model_name: str = "flood-words") -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.calls: list[str] = []
        self.started = asyncio.Event()
        # When set, extract waits until the test sets this event.
        self.gate: asyncio.Event | None = None
        self.error: Exception | None = None
        self.answer: list[ExtractedEvent] | None = None

    async def extract(self, text: str) -> list[ExtractedEvent]:
        self.calls.append(text)
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer
        return [
            ExtractedEvent(
                event_type="flood",
                title=sentence.strip(),
                confidence=0.6,
                metadata={"sentence": index},
            )
            for index, sentence in enumerate(re.split(r"(?<=\.)\s+", text))
            if "flood" in sentence.lower()
        ]
