import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from signalscope.claims.provider import ClaimExtractionProvider
from signalscope.evaluation.evaluation_report import EvaluationReport, evaluation_report
from signalscope.evaluation.extraction.claims import evaluate_claims
from signalscope.evaluation.extraction.dataset import ExtractionDataset
from signalscope.evaluation.extraction.events import evaluate_events
from signalscope.evaluation.extraction.relations import evaluate_relations
from signalscope.evaluation.extraction.scoring import ExtractionScore
from signalscope.events.provider import EventExtractionProvider
from signalscope.relations.provider import RelationExtractionProvider


async def benchmark_structured(
    dataset: ExtractionDataset,
    fingerprint: str,
    event_provider: EventExtractionProvider,
    claim_provider: ClaimExtractionProvider,
    relation_provider: RelationExtractionProvider,
    *,
    timestamp: datetime,
    environment: dict[str, Any] | None = None,
    timer: Callable[[], float] = time.perf_counter,
) -> EvaluationReport:
    event = await _timed(lambda: evaluate_events(dataset, event_provider), timer)
    claim = await _timed(lambda: evaluate_claims(dataset, claim_provider), timer)
    relation = await _timed(lambda: evaluate_relations(dataset, relation_provider), timer)
    return evaluation_report(
        task="structured_extraction",
        model=event[0].model,
        provider=event[0].provider,
        dataset_name=dataset.name,
        dataset_fingerprint=fingerprint,
        created_at=timestamp.isoformat(),
        environment=environment,
        configuration={"records_processed": len(dataset.documents)},
        metrics={
            "production": {"events": _score(event), "claims": _score(claim)},
            "experimental_relation": {"relations": _score(relation)},
        },
        timings={
            "event_seconds": event[1],
            "claim_seconds": claim[1],
            "relation_seconds": relation[1],
        },
        warnings=("Relation metrics are experimental.",),
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
        "parse_validation_failures": 0,
    }
