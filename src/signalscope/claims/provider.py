import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from signalscope.core.errors import ServiceUnavailableError, SignalScopeError
from signalscope.domain.claims.model import (
    CLAIM_TEXT_MAX_LENGTH,
    CLAIM_TYPE_MAX_LENGTH,
    SURFACE_TEXT_MAX_LENGTH,
)
from signalscope.domain.claims.text import normalize_claim_type


class ClaimExtractorUnavailableError(ServiceUnavailableError):
    default_message = "Claim extraction model is not available."


class InvalidExtractedClaimError(SignalScopeError):
    """The model answered with a claim that does not fit the text."""

    default_message = "Claim extraction returned an invalid claim."


@dataclass(frozen=True, slots=True)
class ExtractedClaim:
    # The claim in plain words, such as "Unemployment fell to 5%".
    text: str
    # A short label, such as "statistic" or "quote".
    claim_type: str
    # The words in the chunk that make the claim, at start_char:end_char.
    surface_text: str
    start_char: int
    end_char: int
    # How sure the model is, from 0 to 1, when it says.
    confidence: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ClaimExtractionProvider(Protocol):
    """Finds the claims a text makes, with one model."""

    provider_name: str
    model_name: str

    async def extract(self, text: str) -> list[ExtractedClaim]:
        """Return the claims in text, with offsets into text."""
        ...


async def extract_claims(provider: ClaimExtractionProvider, text: str) -> list[ExtractedClaim]:
    """Extract claims with provider and check each one against the text.

    Claim types come back trimmed and in lower case, and claim text trimmed.
    """
    if not text.strip():
        return []
    claims = await provider.extract(text)
    name = f"{provider.provider_name}/{provider.model_name}"
    checked = []
    for claim in claims:
        problem = claim_problem(claim, text)
        if problem is not None:
            raise InvalidExtractedClaimError(f"Claim extraction model {name} {problem}.")
        checked.append(
            replace(
                claim, text=claim.text.strip(), claim_type=normalize_claim_type(claim.claim_type)
            )
        )
    return checked


def claim_problem(claim: ExtractedClaim, text: str) -> str | None:
    """Say what is wrong with an extracted claim, or return None when it fits the text."""
    if not isinstance(claim.text, str) or not claim.text.strip():
        return "returned a claim without text"
    if len(claim.text.strip()) > CLAIM_TEXT_MAX_LENGTH:
        return f"returned a claim longer than {CLAIM_TEXT_MAX_LENGTH} characters"
    if not isinstance(claim.claim_type, str) or not claim.claim_type.strip():
        return "returned a claim without a type"
    if len(claim.claim_type.strip()) > CLAIM_TYPE_MAX_LENGTH:
        return f"returned a claim type longer than {CLAIM_TYPE_MAX_LENGTH} characters"
    start, end = claim.start_char, claim.end_char
    if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text)):
        return f"returned offsets {start}:{end} outside the text"
    if text[start:end] != claim.surface_text:
        return f"returned text that is not at offsets {start}:{end}"
    if len(claim.surface_text) > SURFACE_TEXT_MAX_LENGTH:
        return f"returned a passage longer than {SURFACE_TEXT_MAX_LENGTH} characters"
    confidence = claim.confidence
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, int | float)
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        return "returned a confidence outside 0 to 1"
    if not isinstance(claim.metadata, Mapping):
        return "returned metadata that is not an object"
    return None
