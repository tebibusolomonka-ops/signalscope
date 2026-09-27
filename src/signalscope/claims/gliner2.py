"""Claim extraction with the shared local GLiNER2 model."""

import logging
from collections.abc import Mapping
from typing import Any

from signalscope.claims.provider import ExtractedClaim, InvalidExtractedClaimError, claim_problem
from signalscope.extraction.gliner2 import StructuredBackend, StructuredSchema, field_text

logger = logging.getLogger(__name__)

CLAIM_RECORD = "claim"
CLAIM_SCHEMA: StructuredSchema = {
    CLAIM_RECORD: (
        "text::str::The claim in plain words",
        "claim_type::str::The kind of claim, such as statement, statistic, prediction, "
        "attribution or announcement",
        "surface_text::str::The exact words in the text that make the claim",
    )
}


class Gliner2ClaimProvider:
    """Finds claims with GLiNER2 structured extraction.

    Claims are statements a text makes. Nothing here says whether they are true.

    The offsets come from finding surface_text in the chunk, exactly as
    written. When the same words appear more than once, each claim takes the
    first place not used by an earlier claim. A record whose words are not in
    the chunk, or that cannot be stored, is skipped with a warning, so one bad
    record does not lose the others. GLiNER2 gives no score for a whole
    record, so confidence stays None.
    """

    def __init__(self, backend: StructuredBackend) -> None:
        self.backend = backend
        self.provider_name = backend.provider_name
        self.model_name = backend.model_name

    async def extract(self, text: str) -> list[ExtractedClaim]:
        output = await self.backend.extract_json(text, CLAIM_SCHEMA)
        records = output.get(CLAIM_RECORD)
        if not isinstance(records, list):
            raise InvalidExtractedClaimError(
                f"Claim extraction model {self.provider_name}/{self.model_name} "
                "returned no list of claims."
            )
        used: set[tuple[int, int]] = set()
        claims = []
        for index, record in enumerate(records):
            claim = _claim(record, text, used)
            problem = "is not a usable claim" if claim is None else claim_problem(claim, text)
            if claim is None or problem is not None:
                logger.warning("Skipped extracted claim %s: %s", index, problem)
                continue
            used.add((claim.start_char, claim.end_char))
            claims.append(claim)
        return claims


def _claim(record: Any, text: str, used: set[tuple[int, int]]) -> ExtractedClaim | None:
    if not isinstance(record, Mapping):
        return None
    claim_text = field_text(record, "text")
    claim_type = field_text(record, "claim_type")
    surface = field_text(record, "surface_text")
    if claim_text is None or claim_type is None or surface is None:
        return None
    start = _first_unused(text, surface, used)
    if start is None:
        return None
    return ExtractedClaim(
        text=claim_text,
        claim_type=claim_type,
        surface_text=surface,
        start_char=start,
        end_char=start + len(surface),
    )


def _first_unused(text: str, surface: str, used: set[tuple[int, int]]) -> int | None:
    """The first start of surface in text that no earlier claim took, if any."""
    start = text.find(surface)
    while start != -1 and (start, start + len(surface)) in used:
        start = text.find(surface, start + 1)
    return None if start == -1 else start
