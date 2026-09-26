"""A fake answer model for tests.

It writes one sentence per evidence item, quoting its title, and cites each
item by its ID. It does not understand the question.
"""

from signalscope.research.generation import AnswerRequest, GeneratedAnswer


class FakeAnswerGenerator:
    def __init__(self, provider_name: str = "test", model_name: str = "echo") -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.requests: list[AnswerRequest] = []
        self.error: Exception | None = None
        # When set, returned as it is instead of the normal answer.
        self.answer: GeneratedAnswer | None = None

    async def generate(self, request: AnswerRequest) -> GeneratedAnswer:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer
        sentences = [
            f"{item.title or 'A source'} is relevant [{item.evidence_id}]."
            for item in request.evidence
        ]
        return GeneratedAnswer(
            text=" ".join(sentences),
            citation_ids=tuple(item.evidence_id for item in request.evidence),
        )
