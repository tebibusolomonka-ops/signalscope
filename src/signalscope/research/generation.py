"""The interface for models that write answers from research evidence.

This module defines what an answer model receives, what it must return, and
checks the shape of what it returns. research.local holds the local model.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from signalscope.core.errors import ServiceUnavailableError
from signalscope.research.evidence import ResearchEvidence

# Evidence IDs look like E1, E2 and so on.
CITATION_ID = re.compile(r"E[1-9][0-9]*")


class AnswerGeneratorUnavailableError(ServiceUnavailableError):
    default_message = "Answer generation is not available."


class InvalidGeneratedAnswerError(ServiceUnavailableError):
    """The model answered, but the answer cannot be shown.

    The message never holds the model's own output.
    """

    default_message = "The answer model returned an answer that cannot be used."


@dataclass(frozen=True, slots=True)
class AnswerRequest:
    question: str
    # The evidence the answer may cite, in order, with IDs E1, E2 and so on.
    evidence: tuple[ResearchEvidence, ...]
    # The same evidence as numbered text blocks, for models that read text.
    context_text: str


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    text: str
    # The evidence IDs the answer relies on, such as ("E1", "E3").
    citation_ids: tuple[str, ...]


class ResearchAnswerGenerator(Protocol):
    """Writes an answer to a question from the evidence it is given, with one model."""

    provider_name: str
    model_name: str

    async def generate(self, request: AnswerRequest) -> GeneratedAnswer: ...


async def generate_answer(
    generator: ResearchAnswerGenerator, request: AnswerRequest
) -> GeneratedAnswer:
    """Ask generator for an answer and check its shape.

    This checks that there is text and that every citation ID looks like E1.
    Whether the IDs match the evidence is checked by validate_citations.
    """
    answer = await generator.generate(request)
    name = f"{generator.provider_name}/{generator.model_name}"
    if not isinstance(answer, GeneratedAnswer):
        raise InvalidGeneratedAnswerError(f"Answer model {name} did not return an answer.")
    if not isinstance(answer.text, str) or not answer.text.strip():
        raise InvalidGeneratedAnswerError(f"Answer model {name} returned an empty answer.")
    if not isinstance(answer.citation_ids, Sequence) or isinstance(answer.citation_ids, str):
        raise InvalidGeneratedAnswerError(
            f"Answer model {name} returned citations that are not a list."
        )
    for citation_id in answer.citation_ids:
        if not isinstance(citation_id, str) or not CITATION_ID.fullmatch(citation_id):
            raise InvalidGeneratedAnswerError(
                f"Answer model {name} returned a citation that is not an evidence ID."
            )
    return GeneratedAnswer(text=answer.text.strip(), citation_ids=tuple(answer.citation_ids))


class DuplicateAnswerGeneratorError(ValueError):
    pass


class AnswerGeneratorRegistry:
    """The answer models this process can use, by provider and model name.

    Models are only added by explicit registration, so a new registry is empty.
    """

    def __init__(self) -> None:
        self._generators: dict[tuple[str, str], ResearchAnswerGenerator] = {}

    def register(self, generator: ResearchAnswerGenerator) -> None:
        key = (generator.provider_name, generator.model_name)
        if key in self._generators:
            raise DuplicateAnswerGeneratorError(
                f"Answer model {key[0]}/{key[1]} is already registered."
            )
        self._generators[key] = generator

    def get(self, provider_name: str, model_name: str) -> ResearchAnswerGenerator:
        generator = self._generators.get((provider_name, model_name))
        if generator is None:
            raise AnswerGeneratorUnavailableError(
                f"Answer model {provider_name}/{model_name} is not configured."
            )
        return generator

    def only(self) -> ResearchAnswerGenerator:
        """The one registered model, for callers that do not name one."""
        if len(self._generators) != 1:
            raise AnswerGeneratorUnavailableError(
                "No answer model is configured."
                if not self._generators
                else "More than one answer model is configured."
            )
        [generator] = self._generators.values()
        return generator

    def keys(self) -> list[tuple[str, str]]:
        """Return the (provider, model) pairs that are registered, sorted."""
        return sorted(self._generators)
