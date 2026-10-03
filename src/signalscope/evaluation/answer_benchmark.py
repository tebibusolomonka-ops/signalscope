import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from signalscope.core.errors import SignalScopeError
from signalscope.evaluation.dataset import EvaluationDataError
from signalscope.evaluation.evaluation_report import EvaluationReport, evaluation_report
from signalscope.research.citations import validate_citations
from signalscope.research.context import context_text
from signalscope.research.evidence import ResearchEvidence
from signalscope.research.generation import AnswerRequest, ResearchAnswerGenerator, generate_answer


@dataclass(frozen=True, slots=True)
class AnswerCase:
    key: str
    question: str
    evidence: tuple[ResearchEvidence, ...]


@dataclass(frozen=True, slots=True)
class AnswerDataset:
    name: str
    prompt_config_version: str
    cases: tuple[AnswerCase, ...]


async def benchmark_answers(
    generator: ResearchAnswerGenerator,
    dataset: AnswerDataset,
    fingerprint: str,
    *,
    timestamp: datetime,
    environment: dict[str, Any] | None = None,
    timer: Callable[[], float] = time.perf_counter,
) -> EvaluationReport:
    parsed = validated = invalid = missing = 0
    latencies = []
    for case in dataset.cases:
        request = AnswerRequest(case.question, case.evidence, context_text(case.evidence))
        started = timer()
        try:
            answer = await generate_answer(generator, request)
            parsed += 1
            allowed = {item.evidence_id for item in case.evidence}
            invalid += len(set(answer.citation_ids) - allowed)
            missing += len(allowed - set(answer.citation_ids))
            validate_citations(answer, case.evidence)
            validated += 1
        except SignalScopeError:
            pass
        latencies.append(timer() - started)
    return evaluation_report(
        task="answer_citation",
        model=generator.model_name,
        provider=generator.provider_name,
        dataset_name=dataset.name,
        dataset_fingerprint=fingerprint,
        created_at=timestamp.isoformat(),
        environment=environment,
        configuration={
            "prompt_config_version": dataset.prompt_config_version,
            "records_processed": len(dataset.cases),
        },
        metrics={
            "json_parse_successes": parsed,
            "citation_validation_successes": validated,
            "invalid_citation_count": invalid,
            "missing_citation_count": missing,
        },
        timings={
            "generation_seconds": sum(latencies),
            "mean_generation_seconds": sum(latencies) / len(latencies),
        },
    )


def load_answer_dataset(path: Path) -> AnswerDataset:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        name = raw["name"]
        version = raw["prompt_config_version"]
        raw_cases = raw["cases"]
        if not isinstance(name, str) or not name.strip() or not isinstance(version, str):
            raise TypeError
        cases = []
        for raw_case in raw_cases:
            evidence = tuple(
                ResearchEvidence(
                    evidence_id=item["id"],
                    document_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{raw_case['key']}:document"),
                    chunk_id=uuid.uuid5(
                        uuid.NAMESPACE_URL, f"{raw_case['key']}:{item['id']}:chunk"
                    ),
                    source_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{raw_case['key']}:source"),
                    title=item.get("title"),
                    url=None,
                    excerpt=item["text"],
                    text=item["text"],
                    chunk_metadata={},
                    scores={},
                )
                for item in raw_case["evidence"]
            )
            if not evidence:
                raise ValueError
            cases.append(AnswerCase(raw_case["key"], raw_case["question"], evidence))
        if not cases:
            raise ValueError
        return AnswerDataset(name, version, tuple(cases))
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise EvaluationDataError(f"Answer benchmark dataset {path} is not valid.") from None
