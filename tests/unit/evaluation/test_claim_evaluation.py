import pytest

from signalscope.claims.provider import ExtractedClaim
from signalscope.evaluation.extraction.claims import evaluate_claims
from signalscope.evaluation.extraction.dataset import (
    ExtractionDataset,
    ExtractionDocument,
    GoldClaim,
)
from signalscope.evaluation.extraction.scoring import ExtractionScore

pytestmark = pytest.mark.anyio

TEXT = "Prices rose 5%. The minister said wages will rise."
PRICES = (0, 15)
WAGES = (34, 50)


class ScriptedClaims:
    provider_name = "test"
    model_name = "scripted"

    def __init__(self, claims: list[ExtractedClaim]) -> None:
        self.claims = claims

    async def extract(self, text: str) -> list[ExtractedClaim]:
        return self.claims if text == TEXT else []


DATASET = ExtractionDataset(
    name="claims",
    documents=(ExtractionDocument("a", TEXT), ExtractionDocument("b", "No claims here.")),
    claims=(
        GoldClaim("a", "statistic", TEXT[slice(*PRICES)], *PRICES),
        GoldClaim("a", "prediction", TEXT[slice(*WAGES)], *WAGES),
    ),
)


def claim(span: tuple[int, int], claim_type: str) -> ExtractedClaim:
    start, end = span
    return ExtractedClaim(
        text=TEXT[start:end],
        claim_type=claim_type,
        surface_text=TEXT[start:end],
        start_char=start,
        end_char=end,
    )


async def score(*claims: ExtractedClaim) -> ExtractionScore:
    return await evaluate_claims(DATASET, ScriptedClaims(list(claims)))


def test_spans() -> None:
    assert TEXT[slice(*PRICES)] == "Prices rose 5%."
    assert TEXT[slice(*WAGES)] == "wages will rise."


async def test_perfect() -> None:
    result = await score(claim(PRICES, "Statistic"), claim(WAGES, " prediction "))

    assert (result.kind, result.gold_count, result.predicted_count, result.matched_count) == (
        "claim",
        2,
        2,
        2,
    )
    assert (result.precision, result.recall, result.f1) == (1.0, 1.0, 1.0)


async def test_missing() -> None:
    result = await score(claim(PRICES, "statistic"))

    assert (result.precision, result.recall) == (1.0, 0.5)
    assert result.documents[0].missed == ("prediction 34:50",)


async def test_extra() -> None:
    result = await score(
        claim(PRICES, "statistic"), claim(WAGES, "prediction"), claim((16, 50), "attribution")
    )

    assert result.precision == pytest.approx(2 / 3)
    assert result.documents[0].extra == ("attribution 16:50",)


async def test_wrong_type() -> None:
    result = await score(claim(PRICES, "prediction"), claim(WAGES, "prediction"))

    assert result.matched_count == 1


async def test_wrong_offsets() -> None:
    # The same words without the full stop do not match.
    result = await score(claim((0, 14), "statistic"), claim(WAGES, "prediction"))

    assert result.matched_count == 1


async def test_duplicate_prediction_matches_once() -> None:
    result = await score(claim(PRICES, "statistic"), claim(PRICES, "statistic"))

    assert (result.matched_count, result.predicted_count) == (1, 2)
    assert result.precision == 0.5


async def test_no_claims_found() -> None:
    result = await score()

    assert (result.predicted_count, result.precision, result.recall, result.f1) == (
        0,
        None,
        0.0,
        None,
    )
    assert [document.gold_count for document in result.documents] == [2, 0]
