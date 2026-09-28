"""Scoring a claim extraction model on an extraction dataset."""

from signalscope.claims.provider import ClaimExtractionProvider, ExtractedClaim, extract_claims
from signalscope.domain.claims.text import normalize_claim_type
from signalscope.evaluation.extraction.dataset import ExtractionDataset, GoldClaim
from signalscope.evaluation.extraction.scoring import ExtractionScore, score_document


def claim_matches(gold: GoldClaim, predicted: ExtractedClaim) -> bool:
    """The same span of the text, exactly, and the same claim type.

    There is no matching by meaning, so a claim found at other offsets does
    not match, even when it says the same thing.
    """
    return (
        gold.start_char == predicted.start_char
        and gold.end_char == predicted.end_char
        and normalize_claim_type(gold.claim_type) == normalize_claim_type(predicted.claim_type)
    )


async def evaluate_claims(
    dataset: ExtractionDataset, provider: ClaimExtractionProvider
) -> ExtractionScore:
    """Run provider on every document and compare its claims with the gold claims.

    Predictions go through the same checks as in the worker, so offsets must
    point at the claimed words.
    """
    documents = []
    for document in dataset.documents:
        gold = [claim for claim in dataset.claims if claim.document_key == document.key]
        predicted = await extract_claims(provider, document.text)
        documents.append(
            score_document(
                document.key,
                gold,
                predicted,
                claim_matches,
                lambda claim: f"{claim.claim_type} {claim.start_char}:{claim.end_char}",
                lambda claim: f"{claim.claim_type} {claim.start_char}:{claim.end_char}",
            )
        )
    return ExtractionScore(
        dataset=dataset.name,
        kind="claim",
        provider=provider.provider_name,
        model=provider.model_name,
        documents=tuple(documents),
    )
