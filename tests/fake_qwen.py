"""A fake Transformers tokenizer and model that stand in for Qwen in tests.

The fake model does not read the prompt tokens. It answers from the chat
messages the tokenizer last saw: by default a JSON answer that names every
evidence ID in them. Nothing is downloaded.
"""

import json
import re
import threading
from pathlib import Path
from typing import Any

PROMPT_TOKENS = [101, 102, 103]


class FakeInputs(dict[str, Any]):
    def __init__(self, owner: "FakeQwen") -> None:
        super().__init__(input_ids=[list(PROMPT_TOKENS)], attention_mask=[[1, 1, 1]])
        self.owner = owner

    def to(self, device: str) -> "FakeInputs":
        self.owner.input_devices.append(device)
        return self


class FakeQwen:
    """Records every call. Set reply to change what the model writes."""

    def __init__(self, device: str = "cpu") -> None:
        self.device = device
        self.messages: list[list[dict[str, str]]] = []
        self.template_options: list[dict[str, Any]] = []
        self.generate_options: list[dict[str, Any]] = []
        self.input_devices: list[str] = []
        self.threads: list[str] = []
        self.reply: str | None = None
        self.load_calls: list[tuple[str, str, Path | None]] = []

    # The tokenizer side.

    def apply_chat_template(self, messages: list[dict[str, str]], **options: Any) -> str:
        self.messages.append(messages)
        self.template_options.append(options)
        return "<prompt>"

    def __call__(self, texts: list[str], return_tensors: str) -> FakeInputs:
        assert (texts, return_tensors) == (["<prompt>"], "pt")
        return FakeInputs(self)

    def decode(self, tokens: list[Any], skip_special_tokens: bool) -> str:
        assert skip_special_tokens
        return "".join(str(token) for token in tokens)

    # The model side.

    def generate(self, **options: Any) -> list[list[Any]]:
        self.generate_options.append(options)
        self.threads.append(threading.current_thread().name)
        return [[*PROMPT_TOKENS, self._answer()]]

    def _answer(self) -> str:
        if self.reply is not None:
            return self.reply
        ids = list(dict.fromkeys(re.findall(r"\[(E\d+)\]", self.messages[-1][-1]["content"])))
        text = " ".join(f"The evidence says so [{evidence_id}]." for evidence_id in ids)
        return json.dumps({"text": text, "citation_ids": ids})

    def load(
        self, model: str, device: str, cache_dir: Path | None
    ) -> tuple["FakeQwen", "FakeQwen"]:
        """A loader for the generator: the fake is both tokenizer and model."""
        self.load_calls.append((model, device, cache_dir))
        return self, self
