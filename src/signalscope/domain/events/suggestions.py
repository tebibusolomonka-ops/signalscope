import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import NotFoundError
from signalscope.domain.events.cluster import EventClusterMember
from signalscope.domain.events.model import Event
from signalscope.embeddings.models import MULTILINGUAL_E5_SMALL
from signalscope.embeddings.provider import EmbeddingInputRole, embed
from signalscope.embeddings.registry import EmbeddingProviderRegistry

DEFAULT_SUGGESTION_LIMIT = 10
# The most events compared with one event, so the whole table is never embedded.
MAX_CANDIDATES = 200
# Dated candidates must be this close to a dated event.
DATE_WINDOW_DAYS = 7


@dataclass(frozen=True, slots=True)
class EventLinkSuggestion:
    candidate_event_id: uuid.UUID
    # The cluster the candidate is in, if any.
    cluster_id: uuid.UUID | None
    title: str
    occurred_at: datetime | None
    # Cosine similarity of the two event texts, from -1 to 1. Not a probability.
    similarity: float


def event_text(event: Event) -> str:
    """The text an event is compared by: its type, title and summary. No IDs."""
    parts = [f"{event.event_type}: {event.title.strip()}"]
    if event.summary and event.summary.strip():
        parts.append(event.summary.strip())
    return "\n".join(parts)


class EventLinkSuggestionService:
    """Suggests events that may report the same thing as one event, by meaning.

    These are suggestions for a person to review. They never change cluster
    membership, and there is no similarity threshold that links anything. The
    exact linker stays the only automatic way events are linked.

    Candidates are limited before anything is embedded: the same event type,
    not already in the event's cluster, and, when the event has a date,
    either undated or within DATE_WINDOW_DAYS of it. At most MAX_CANDIDATES
    newest candidates are compared.
    """

    def __init__(self, session: AsyncSession, providers: EmbeddingProviderRegistry) -> None:
        self.session = session
        self.providers = providers

    async def suggest(
        self, event_id: uuid.UUID, limit: int = DEFAULT_SUGGESTION_LIMIT
    ) -> list[EventLinkSuggestion]:
        """Candidates for event_id, most similar first."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        spec = MULTILINGUAL_E5_SMALL
        # Checked first, so no query runs when there is no model.
        provider = self.providers.get(spec.provider, spec.model)
        event = await self.session.get(Event, event_id)
        if event is None:
            raise NotFoundError("Event was not found.")
        candidates = await self._candidates(event)
        if not candidates:
            return []
        texts = [event_text(event), *(event_text(candidate) for candidate, _ in candidates)]
        # Both sides are the same kind of text, so both use the query role.
        target, *vectors = await embed(provider, texts, EmbeddingInputRole.QUERY)
        suggestions = [
            EventLinkSuggestion(
                candidate_event_id=candidate.id,
                cluster_id=cluster_id,
                title=candidate.title,
                occurred_at=candidate.occurred_at,
                similarity=_cosine(target, vector),
            )
            for (candidate, cluster_id), vector in zip(candidates, vectors, strict=True)
        ]
        suggestions.sort(key=lambda item: (-item.similarity, str(item.candidate_event_id)))
        return suggestions[:limit]

    async def _candidates(self, event: Event) -> list[tuple[Event, uuid.UUID | None]]:
        own_cluster = await self.session.scalar(
            select(EventClusterMember.cluster_id).where(EventClusterMember.event_id == event.id)
        )
        statement = (
            select(Event, EventClusterMember.cluster_id)
            .outerjoin(EventClusterMember, EventClusterMember.event_id == Event.id)
            .where(Event.id != event.id, Event.event_type == event.event_type)
        )
        if own_cluster is not None:
            statement = statement.where(
                or_(
                    EventClusterMember.cluster_id.is_(None),
                    EventClusterMember.cluster_id != own_cluster,
                )
            )
        if event.occurred_at is not None:
            window = timedelta(days=DATE_WINDOW_DAYS)
            statement = statement.where(
                or_(
                    Event.occurred_at.is_(None),
                    Event.occurred_at.between(
                        event.occurred_at - window, event.occurred_at + window
                    ),
                )
            )
        rows = await self.session.execute(
            statement.order_by(Event.created_at.desc(), Event.id).limit(MAX_CANDIDATES)
        )
        return [(candidate, cluster_id) for candidate, cluster_id in rows]


def _cosine(first: Sequence[float], second: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(first, second, strict=True))
    norms = math.sqrt(sum(a * a for a in first)) * math.sqrt(sum(b * b for b in second))
    return dot / norms if norms else 0.0
