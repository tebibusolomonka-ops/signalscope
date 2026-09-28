"""Scoring a relation extraction model on an extraction dataset."""

import re
import unicodedata

from signalscope.evaluation.extraction.dataset import ExtractionDataset, GoldRelation
from signalscope.evaluation.extraction.scoring import ExtractionScore, score_document
from signalscope.relations.provider import (
    ExtractedRelation,
    RelationExtractionProvider,
    extract_relations,
)

WHITESPACE = re.compile(r"\s+")


def normalize_words(text: str) -> str:
    """NFKC, trimmed and collapsed spaces, folded case. Punctuation and numbers stay."""
    return WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


def relation_matches(gold: GoldRelation, predicted: ExtractedRelation) -> bool:
    """The same subject, relation type and object, in the same direction.

    Words are compared after normalize_words, and nothing else: no similarity
    and no entity resolution. "Acme works_for Ana" does not match "Ana
    works_for Acme".
    """
    return (
        normalize_words(gold.subject_text) == normalize_words(predicted.subject_text)
        and gold.relation_type.strip().lower() == predicted.relation_type.strip().lower()
        and normalize_words(gold.object_text) == normalize_words(predicted.object_text)
    )


def _describe(relation: GoldRelation | ExtractedRelation) -> str:
    return f"{relation.subject_text} {relation.relation_type} {relation.object_text}"


async def evaluate_relations(
    dataset: ExtractionDataset, provider: RelationExtractionProvider
) -> ExtractionScore:
    """Run provider on every document and compare its relations with the gold relations."""
    documents = []
    for document in dataset.documents:
        gold = [relation for relation in dataset.relations if relation.document_key == document.key]
        predicted = await extract_relations(provider, document.text)
        documents.append(
            score_document(document.key, gold, predicted, relation_matches, _describe, _describe)
        )
    return ExtractionScore(
        dataset=dataset.name,
        kind="relation",
        provider=provider.provider_name,
        model=provider.model_name,
        documents=tuple(documents),
    )
