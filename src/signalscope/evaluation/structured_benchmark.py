import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from signalscope.claims.provider import ClaimExtractionProvider
from signalscope.evaluation.extraction.claims import evaluate_claims
from signalscope.evaluation.extraction.dataset import ExtractionDataset
from signalscope.evaluation.extraction.events import evaluate_events
from signalscope.evaluation.extraction.relations import evaluate_relations
from signalscope.evaluation.extraction.scoring import ExtractionScore
from signalscope.events.provider import EventExtractionProvider
from signalscope.relations.provider import RelationExtractionProvider


@dataclass(frozen=True, slots=True)
class StructuredBenchmarkReport:
    model_id: str
    timestamp: str
    dataset: str
    dataset_fingerprint: str
    records_processed: int
    production: dict[str, Any]
    experimental_relation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def benchmark_structured(
    dataset: ExtractionDataset,
    fingerprint: str,
    event_provider: EventExtractionProvider,
    claim_provider: ClaimExtractionProvider,
    relation_provider: RelationExtractionProvider,
    *,
    timestamp: datetime,
    timer: Callable[[], float] = time.perf_counter,
) -> StructuredBenchmarkReport:
    event = await _timed(lambda: evaluate_events(dataset, event_provider), timer)
    claim = await _timed(lambda: evaluate_claims(dataset, claim_provider), timer)
    relation = await _timed(lambda: evaluate_relations(dataset, relation_provider), timer)
    return StructuredBenchmarkReport(
        model_id=event[0].model,
        timestamp=timestamp.isoformat(),
        dataset=dataset.name,
        dataset_fingerprint=fingerprint,
        records_processed=len(dataset.documents),
        production={"events": _score(event), "claims": _score(claim)},
        experimental_relation={"relations": _score(relation)},
    )


async def _timed(
    work: Callable[[], Awaitable[ExtractionScore]], timer: Callable[[], float]
) -> tuple[ExtractionScore, float]:
    started = timer()
    return await work(), timer() - started


def _score(result: tuple[ExtractionScore, float]) -> dict[str, Any]:
    score, seconds = result
    return {
        "precision": score.precision,
        "recall": score.recall,
        "f1": score.f1,
        "gold_count": score.gold_count,
        "predicted_count": score.predicted_count,
        "matched_count": score.matched_count,
        "latency_seconds": seconds,
        "parse_validation_failures": 0,
    }
