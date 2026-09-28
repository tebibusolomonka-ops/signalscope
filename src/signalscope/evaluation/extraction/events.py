"""Scoring an event extraction model on an extraction dataset."""

from datetime import UTC

from signalscope.domain.events.cluster import normalize_event_title
from signalscope.evaluation.extraction.dataset import ExtractionDataset, GoldEvent
from signalscope.evaluation.extraction.scoring import ExtractionScore, score_document
from signalscope.events.provider import EventExtractionProvider, ExtractedEvent, extract_events


def event_matches(gold: GoldEvent, predicted: ExtractedEvent) -> bool:
    """Same type and normalized title, and the same UTC day when both have a date.

    The rules are the ones the exact event linker uses. A prediction without a
    date can still match a gold event with one.
    """
    if gold.event_type.strip().lower() != predicted.event_type.strip().lower():
        return False
    if normalize_event_title(gold.title) != normalize_event_title(predicted.title):
        return False
    if gold.occurred_at is not None and predicted.occurred_at is not None:
        return gold.occurred_at.astimezone(UTC).date() == (
            predicted.occurred_at.astimezone(UTC).date()
        )
    return True


async def evaluate_events(
    dataset: ExtractionDataset, provider: EventExtractionProvider
) -> ExtractionScore:
    """Run provider on every document and compare its events with the gold events.

    Predictions go through the same checks as in the worker, so a model that
    returns an event that cannot be stored fails the evaluation.
    """
    documents = []
    for document in dataset.documents:
        gold = [event for event in dataset.events if event.document_key == document.key]
        predicted = await extract_events(provider, document.text)
        documents.append(
            score_document(
                document.key,
                gold,
                predicted,
                event_matches,
                lambda event: f"{event.event_type}: {event.title}",
                lambda event: f"{event.event_type}: {event.title}",
            )
        )
    return ExtractionScore(
        dataset=dataset.name,
        kind="event",
        provider=provider.provider_name,
        model=provider.model_name,
        documents=tuple(documents),
    )
