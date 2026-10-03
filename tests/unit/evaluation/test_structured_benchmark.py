from datetime import UTC, datetime

import pytest

from signalscope.claims.provider import ExtractedClaim
from signalscope.evaluation.extraction.dataset import (
    ExtractionDataset,
    ExtractionDocument,
    GoldClaim,
    GoldEvent,
    GoldRelation,
)
from signalscope.evaluation.structured_benchmark import benchmark_structured
from signalscope.events.provider import ExtractedEvent
from signalscope.relations.provider import ExtractedRelation


class Provider:
    provider_name = "fake"
    model_name = "fake-structured"

    async def extract(self, text: str):
        return []


class Events(Provider):
    async def extract(self, text: str):
        return [ExtractedEvent(event_type="report", title="Harbour report")]


class Claims(Provider):
    async def extract(self, text: str):
        return [
            ExtractedClaim(
                claim_type="statement",
                text="Harbour",
                surface_text="Harbour",
                start_char=0,
                end_char=7,
            )
        ]


class Relations(Provider):
    async def extract(self, text: str):
        return [ExtractedRelation("Harbour", "near", "port")]


@pytest.mark.anyio
async def test_structured_report_separates_relation_metrics() -> None:
    data = ExtractionDataset(
        "structured",
        (ExtractionDocument("d1", "Harbour port"),),
        (GoldEvent("d1", "report", "Harbour report"),),
        (GoldClaim("d1", "statement", "Harbour", 0, 7),),
        (GoldRelation("d1", "Harbour", "near", "port"),),
    )
    report = await benchmark_structured(
        data,
        "a" * 64,
        Events(),  # type: ignore[arg-type]
        Claims(),  # type: ignore[arg-type]
        Relations(),  # type: ignore[arg-type]
        timestamp=datetime(2026, 10, 3, tzinfo=UTC),
    )
    assert report.metrics["production"]["events"]["f1"] == 1.0
    assert report.metrics["production"]["claims"]["f1"] == 1.0
    assert report.metrics["experimental_relation"]["relations"]["f1"] == 1.0
