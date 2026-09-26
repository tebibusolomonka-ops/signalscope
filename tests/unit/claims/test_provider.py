from typing import Any

import pytest

from fake_claims import FakeClaimExtractor
from signalscope.claims.provider import (
    ClaimExtractionProvider,
    ClaimExtractorUnavailableError,
    ExtractedClaim,
    InvalidExtractedClaimError,
    extract_claims,
)
from signalscope.claims.registry import ClaimExtractorRegistry, DuplicateClaimExtractorError
from signalscope.core.errors import ServiceUnavailableError

pytestmark = pytest.mark.anyio

TEXT = "The ministry spoke. Unemployment fell to 5%. Prices rose 3% in May."


def claim(**values: Any) -> ExtractedClaim:
    fields: dict[str, Any] = {
        "text": "Unemployment fell to 5%",
        "claim_type": "statistic",
        "surface_text": "Unemployment fell to 5%",
        "start_char": 20,
        "end_char": 43,
    }
    return ExtractedClaim(**(fields | values))


def test_fake_extractor_follows_the_protocol() -> None:
    extractor: ClaimExtractionProvider = FakeClaimExtractor()

    assert (extractor.provider_name, extractor.model_name) == ("test", "number-sentences")


async def test_valid_claims() -> None:
    claims = await extract_claims(FakeClaimExtractor(), TEXT)

    assert [(item.text, item.claim_type) for item in claims] == [
        ("Unemployment fell to 5%", "statistic"),
        ("Prices rose 3% in May", "statistic"),
    ]
    assert all(TEXT[item.start_char : item.end_char] == item.surface_text for item in claims)


async def test_claim_text_and_type_are_tidied() -> None:
    extractor = FakeClaimExtractor()
    extractor.answer = [claim(text="  Unemployment fell to 5% ", claim_type=" STATISTIC ")]

    [found] = await extract_claims(extractor, TEXT)

    assert (found.text, found.claim_type) == ("Unemployment fell to 5%", "statistic")
    # The passage from the chunk is left as it is.
    assert found.surface_text == "Unemployment fell to 5%"


async def test_blank_text_calls_nothing() -> None:
    extractor = FakeClaimExtractor()

    assert await extract_claims(extractor, " ") == []
    assert extractor.calls == []


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"text": " "}, "without text"),
        ({"text": "x" * 501}, "longer than 500"),
        ({"claim_type": ""}, "without a type"),
        ({"start_char": -1}, "offsets -1:43 outside the text"),
        ({"end_char": 999}, "outside the text"),
        ({"start_char": 21}, "not at offsets 21:43"),
        ({"surface_text": "unemployment fell to 5%"}, "not at offsets 20:43"),
        ({"confidence": 2}, "confidence outside 0 to 1"),
        ({"confidence": float("nan")}, "confidence outside 0 to 1"),
        ({"metadata": ["x"]}, "metadata that is not an object"),
    ],
    ids=[
        "blank text",
        "long text",
        "blank type",
        "negative start",
        "end past text",
        "wrong offsets",
        "surface mismatch",
        "confidence above one",
        "confidence nan",
        "metadata list",
    ],
)
async def test_invalid_claims_are_rejected(values: dict[str, Any], message: str) -> None:
    extractor = FakeClaimExtractor()
    extractor.answer = [claim(**values)]

    with pytest.raises(InvalidExtractedClaimError, match=message) as error:
        await extract_claims(extractor, TEXT)

    assert "test/number-sentences" in str(error.value)


def test_registry() -> None:
    registry = ClaimExtractorRegistry()
    first = FakeClaimExtractor()

    assert registry.keys() == []
    registry.register(first)

    assert registry.get("test", "number-sentences") is first
    with pytest.raises(DuplicateClaimExtractorError, match="already registered"):
        registry.register(FakeClaimExtractor())
    with pytest.raises(ClaimExtractorUnavailableError, match="test/x is not configured") as error:
        registry.get("test", "x")
    assert isinstance(error.value, ServiceUnavailableError)
