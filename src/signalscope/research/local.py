"""A local answer model run with the Transformers library.

The library, and PyTorch with it, is an optional extra. It is only imported
when the model is first used, so SignalScope runs without it.
"""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from signalscope.research.generation import (
    AnswerGeneratorUnavailableError,
    AnswerRequest,
    GeneratedAnswer,
    InvalidGeneratedAnswerError,
)

QWEN_PROVIDER = "transformers"
QWEN_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
DEFAULT_DEVICE = "cpu"
DEFAULT_MAX_NEW_TOKENS = 512

SYSTEM_PROMPT = """You answer questions using only the evidence given to you.
Rules:
- Use only the evidence below. Do not use outside knowledge.
- Every factual statement must cite the evidence it comes from, like [E1].
- Only cite evidence IDs that appear in the evidence.
- If the evidence does not answer the question, say so, and cite the evidence you checked.
- Return only a JSON object, with no other text and no markdown:
{"text": "The answer, with citations like [E1].", "citation_ids": ["E1"]}
- citation_ids lists every ID the text cites, once each, and no other IDs."""


class LocalAnswersNotInstalledError(AnswerGeneratorUnavailableError):
    default_message = (
        "Local answers need the local-answers extra. "
        'Install it with: pip install -e ".[local-answers]"'
    )


# The tokenizer and model objects from Transformers. They are only used
# through the few methods called below.
TokenizerAndModel = tuple[Any, Any]
# Loads the tokenizer and model from a name, a device and an optional cache folder.
ModelLoader = Callable[[str, str, Path | None], TokenizerAndModel]


def load_qwen(model: str, device: str, cache_dir: Path | None) -> TokenizerAndModel:
    """Load the tokenizer and model, downloading them into the cache on first use."""
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as error:
        raise LocalAnswersNotInstalledError() from error
    tokenizer = AutoTokenizer.from_pretrained(model, cache_dir=cache_dir)
    loaded = AutoModelForCausalLM.from_pretrained(model, cache_dir=cache_dir, torch_dtype="auto")
    loaded.to(device)
    loaded.eval()
    return tokenizer, loaded


def answer_messages(request: AnswerRequest) -> list[dict[str, str]]:
    """The chat messages for one question.

    The model sees only the question and, for each piece of evidence, its ID,
    title and text.
    """
    blocks = [
        f"[{item.evidence_id}]\nTitle: {item.title or '(no title)'}\nText: {item.text}"
        for item in request.evidence
    ]
    evidence = "\n\n".join(blocks)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Evidence:\n\n{evidence}\n\nQuestion: {request.question}"},
    ]


def parse_answer(output: str, name: str) -> GeneratedAnswer:
    """Read the model output, which must be exactly one JSON answer object.

    JSON is not searched for inside other text. The errors never quote the output.
    """
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        raise InvalidGeneratedAnswerError(
            f"Answer model {name} did not return a JSON answer."
        ) from None
    if not isinstance(data, dict) or set(data) != {"text", "citation_ids"}:
        raise InvalidGeneratedAnswerError(
            f"Answer model {name} returned JSON without exactly text and citation_ids."
        )
    text, citation_ids = data["text"], data["citation_ids"]
    if not isinstance(text, str) or not isinstance(citation_ids, list):
        raise InvalidGeneratedAnswerError(f"Answer model {name} returned fields of the wrong type.")
    if not all(isinstance(citation_id, str) for citation_id in citation_ids):
        raise InvalidGeneratedAnswerError(
            f"Answer model {name} returned citations that are not text."
        )
    return GeneratedAnswer(text=text, citation_ids=tuple(citation_ids))


class Qwen3LocalAnswerGenerator:
    """Qwen/Qwen3-4B-Instruct-2507, run locally, answering only from given evidence.

    Generation is greedy, so the same prompt gives the same answer. The model
    is loaded on first use, and runs in a worker thread, because it is slow and
    would block the event loop. Its answer still goes through the citation
    checks of the research service before anyone sees it.
    """

    provider_name = QWEN_PROVIDER
    model_name = QWEN_MODEL

    def __init__(
        self,
        device: str = DEFAULT_DEVICE,
        max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
        cache_dir: Path | None = None,
        loader: ModelLoader = load_qwen,
    ) -> None:
        if max_new_tokens < 1:
            raise ValueError("max_new_tokens must be at least 1")
        self.device = device
        self.max_new_tokens = max_new_tokens
        self.cache_dir = cache_dir
        self.loader = loader
        self._loaded: TokenizerAndModel | None = None
        self._load_lock = asyncio.Lock()

    async def generate(self, request: AnswerRequest) -> GeneratedAnswer:
        tokenizer, model = await self._load()
        output = await asyncio.to_thread(self._complete, tokenizer, model, answer_messages(request))
        return parse_answer(output.strip(), f"{self.provider_name}/{self.model_name}")

    def _complete(self, tokenizer: Any, model: Any, messages: list[dict[str, str]]) -> str:
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer([prompt], return_tensors="pt").to(model.device)
        output = model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False)
        # The output starts with the prompt tokens. Only the new ones are the answer.
        new_tokens = output[0][len(inputs["input_ids"][0]) :]
        answer: str = tokenizer.decode(new_tokens, skip_special_tokens=True)
        return answer

    async def _load(self) -> TokenizerAndModel:
        # The lock stops two first calls at the same time from loading the model twice.
        async with self._load_lock:
            if self._loaded is None:
                self._loaded = await asyncio.to_thread(
                    self.loader, self.model_name, self.device, self.cache_dir
                )
        return self._loaded
