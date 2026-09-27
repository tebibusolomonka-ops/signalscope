"""The GLiNER2 claim provider, with a fake backend in place of the model.

Nothing here downloads or loads model files.
"""

from dataclasses import fields
from typing import Any

import pytest

from signalscope.claims.gliner2 import CLAIM_SCHEMA, Gliner2ClaimProvider
from signalscope.claims.provider import ExtractedClaim, InvalidExtractedClaimError, extract_claims
from signalscope.extraction.gliner2 import StructuredSchema

pytestmark = pytest.mark.anyio

TEXT = "Unemployment fell to 5%. The minister said prices will rise. Unemployment fell to 5%."
FELL = "Unemployment fell to 5%."


class FakeBackend:
    provider_name = "gliner2"
    model_name = "fastino/gliner2.5-multi-v1"

    def __init__(self, output: Any) -> None:
        self.output = output
        self.calls: list[tuple[str, StructuredSchema]] = []

    async def extract_json(self, text: str, schema: StructuredSchema) -> Any:
        self.calls.append((text, schema))
        return self.output


def provider(*records: Any) -> Gliner2ClaimProvider:
    return Gliner2ClaimProvider(FakeBackend({"claim": list(records)}))


def record(surface: str, claim_type: str = "statistic", text: str | None = None) -> dict[str, Any]:
    return {"text": text or surface.rstrip("."), "claim_type": claim_type, "surface_text": surface}


def test_identity_comes_from_the_backend() -> None:
    found = provider()

    assert (found.provider_name, found.model_name) == ("gliner2", "fastino/gliner2.5-multi-v1")


async def test_one_claim_with_exact_offsets() -> None:
    backend = FakeBackend({"claim": [record("prices will rise", " Prediction ")]})

    [claim] = await extract_claims(Gliner2ClaimProvider(backend), TEXT)

    assert (claim.text, claim.claim_type, claim.surface_text) == (
        "prices will rise",
        "prediction",
        "prices will rise",
    )
    assert TEXT[claim.start_char : claim.end_char] == "prices will rise"
    assert (claim.start_char, claim.confidence) == (43, None)
    assert backend.calls == [(TEXT, CLAIM_SCHEMA)]


async def test_several_claims() -> None:
    claims = await extract_claims(
        provider(
            record(FELL, "statistic", "Unemployment fell to 5 percent"),
            record("The minister said prices will rise.", "attribution"),
        ),
        TEXT,
    )

    assert [(claim.claim_type, claim.start_char) for claim in claims] == [
        ("statistic", 0),
        ("attribution", 25),
    ]
    assert claims[0].text == "Unemployment fell to 5 percent"


async def test_repeated_words_take_the_next_unused_place() -> None:
    claims = await provider(record(FELL), record(FELL), record(FELL)).extract(TEXT)

    # The words appear twice, so the third claim has no place left and is skipped.
    assert [(claim.start_char, claim.end_char) for claim in claims] == [(0, 24), (61, 85)]
    assert all(TEXT[claim.start_char : claim.end_char] == FELL for claim in claims)


async def test_surface_text_is_trimmed_but_otherwise_exact() -> None:
    [claim] = await provider(record(f"  {FELL} ")).extract(TEXT)

    assert (claim.surface_text, claim.start_char) == (FELL, 0)


async def test_quote_not_in_the_text_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    claims = await provider(
        record("Unemployment fell to five percent."),
        record("unemployment fell to 5%."),
        record(FELL),
    ).extract(TEXT)

    assert [claim.start_char for claim in claims] == [0]
    assert caplog.text.count("Skipped extracted claim") == 2


async def test_malformed_items_are_skipped(caplog: pytest.LogCaptureFixture) -> None:
    claims = await provider(
        "not an object",
        {"claim_type": "statistic", "surface_text": FELL},
        {"text": "No type", "surface_text": FELL},
        {"text": "No quote", "claim_type": "statistic"},
        record(FELL, "x" * 51),
        record(FELL),
    ).extract(TEXT)

    assert len(claims) == 1
    assert caplog.text.count("Skipped extracted claim") == 5


@pytest.mark.parametrize("output", [{}, {"claim": "text"}, {"claim": None}])
async def test_response_without_a_claim_list_fails(output: Any) -> None:
    with pytest.raises(InvalidExtractedClaimError, match="no list of claims"):
        await Gliner2ClaimProvider(FakeBackend(output)).extract(TEXT)


def test_claims_carry_no_truth_judgement() -> None:
    names = {field.name for field in fields(ExtractedClaim)}
    schema_fields = {spec.split("::")[0] for spec in CLAIM_SCHEMA["claim"]}

    assert schema_fields == {"text", "claim_type", "surface_text"}
    for word in ("true", "false", "verdict", "veracity", "credib", "misinformation"):
        assert not any(word in name for name in names | schema_fields)
