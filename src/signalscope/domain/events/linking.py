import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.events.cluster import (
    EventCluster,
    EventClusterMember,
    normalize_event_title,
)
from signalscope.domain.events.model import EVENT_TITLE_MAX_LENGTH, Event

DEFAULT_LINK_LIMIT = 500


@dataclass(frozen=True, slots=True)
class EventLink:
    cluster_id: uuid.UUID
    # True when this event started a new cluster.
    created_cluster: bool


@dataclass(frozen=True, slots=True)
class EventLinkingResult:
    events_checked: int = 0
    events_linked: int = 0
    clusters_created: int = 0


class EventLinkingService:
    """Puts events that report the same thing into one cluster, across documents.

    This first version only links exact matches: the same event type and the
    same normalized title. When both events have a time, they must also fall
    on the same UTC calendar day. An event without a time can join a cluster
    with the same type and title. There is no fuzzy or meaning-based matching.

    Each event is linked in its own transaction. The event row is locked, and
    a lock on its type and title stops two workers from starting two clusters
    for the same thing at once.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def link_unclustered(self, limit: int = DEFAULT_LINK_LIMIT) -> EventLinkingResult:
        """Link up to limit events that are in no cluster yet, oldest first."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        async with self.session_factory() as session:
            event_ids = list(
                await session.scalars(
                    select(Event.id)
                    .where(~exists().where(EventClusterMember.event_id == Event.id))
                    .order_by(Event.created_at, Event.id)
                    .limit(limit)
                )
            )
        linked = created = 0
        for event_id in event_ids:
            link = await self.link_event(event_id)
            if link is not None:
                linked += 1
                created += link.created_cluster
        return EventLinkingResult(
            events_checked=len(event_ids), events_linked=linked, clusters_created=created
        )

    async def link_event(self, event_id: uuid.UUID) -> EventLink | None:
        """Put one event in a cluster and return it.

        An event that is already in a cluster keeps it. Returns None when the
        event does not exist or its title is too long to match once normalized.
        """
        async with self.session_factory() as session:
            try:
                link = await _link(session, event_id)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return link


async def _link(session: AsyncSession, event_id: uuid.UUID) -> EventLink | None:
    event = await session.get(Event, event_id, with_for_update=True, populate_existing=True)
    if event is None:
        return None
    member = await session.get(EventClusterMember, event_id)
    if member is not None:
        return EventLink(member.cluster_id, created_cluster=False)
    event_type = event.event_type.strip().lower()
    normalized = normalize_event_title(event.title)
    if len(normalized) > EVENT_TITLE_MAX_LENGTH:
        return None
    # Waits for any other transaction linking an event with the same type and title.
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtext(f"{event_type}\n{normalized}")))
    )
    cluster = await _matching_cluster(session, event_type, normalized, event.occurred_at)
    created = cluster is None
    if cluster is None:
        cluster = EventCluster(
            event_type=event_type,
            canonical_title=event.title.strip(),
            normalized_title=normalized,
            occurred_at=event.occurred_at,
        )
        session.add(cluster)
        await session.flush()
    session.add(EventClusterMember(cluster_id=cluster.id, event_id=event.id))
    await session.flush()
    await _refresh_canonical_values(session, cluster)
    return EventLink(cluster.id, created_cluster=created)


async def _matching_cluster(
    session: AsyncSession, event_type: str, normalized: str, occurred_at: datetime | None
) -> EventCluster | None:
    """The cluster the event belongs in, if any.

    A cluster on the same day comes first. Otherwise, and for events without a
    time, the oldest matching cluster is used, so the choice never depends on
    the order the database returns rows in.
    """
    candidates = await session.scalars(
        select(EventCluster)
        .where(EventCluster.event_type == event_type, EventCluster.normalized_title == normalized)
        .order_by(EventCluster.created_at, EventCluster.id)
        .with_for_update()
    )
    matches = [
        cluster
        for cluster in candidates
        if occurred_at is None
        or cluster.occurred_at is None
        or _utc_day(cluster.occurred_at) == _utc_day(occurred_at)
    ]
    same_day = [cluster for cluster in matches if cluster.occurred_at is not None]
    if occurred_at is not None and same_day:
        return same_day[0]
    return matches[0] if matches else None


async def _refresh_canonical_values(session: AsyncSession, cluster: EventCluster) -> None:
    """Take the title from the oldest member event and the earliest known time.

    Both come from all members, so they are the same whatever order events
    were linked in.
    """
    members = select(Event).join(EventClusterMember, EventClusterMember.event_id == Event.id)
    members = members.where(EventClusterMember.cluster_id == cluster.id)
    first = await session.scalar(members.order_by(Event.created_at, Event.id).limit(1))
    earliest = await session.scalar(
        select(func.min(Event.occurred_at))
        .join(EventClusterMember, EventClusterMember.event_id == Event.id)
        .where(EventClusterMember.cluster_id == cluster.id)
    )
    if first is not None:
        cluster.canonical_title = first.title.strip()
    cluster.occurred_at = earliest
    await session.flush()


def _utc_day(value: datetime) -> date:
    return value.astimezone(UTC).date()
