import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.db.errors import is_unique_violation
from signalscope.domain.claims.model import Claim
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.cluster import EventCluster
from signalscope.domain.events.model import Event
from signalscope.domain.investigations.item import InvestigationItem, InvestigationItemType
from signalscope.domain.investigations.model import Investigation, InvestigationStatus
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.research.turn import ResearchTurn
from signalscope.domain.sources.model import Source

CLOSED_ERROR = "Investigation is closed. Reopen it to change it."

# Takes the session and a reference ID. Returns the snapshot, or None when the
# record does not exist.
SnapshotReader = Callable[[AsyncSession, uuid.UUID], Awaitable[dict[str, Any] | None]]


class InvestigationService:
    """Saved investigations and the references saved in them.

    A closed investigation is read only: its details and items cannot change,
    and it cannot be deleted, until it is opened again.

    Each item keeps a small snapshot of the record, taken when it is saved, and
    never updated. Snapshots hold names, titles, types and dates, never full
    document text, vectors, files or prompts.

    Writes commit before they return.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, title: str, description: str | None = None) -> Investigation:
        investigation = Investigation(title=title, description=description)
        self.session.add(investigation)
        await self._commit()
        return investigation

    async def get(self, investigation_id: uuid.UUID) -> Investigation:
        investigation = await self.session.get(Investigation, investigation_id)
        if investigation is None:
            raise NotFoundError("Investigation was not found.")
        return investigation

    async def list_page(
        self, status: InvestigationStatus | None, limit: int, offset: int
    ) -> tuple[list[Investigation], int]:
        """Newest first, with the total that match."""
        conditions = [] if status is None else [Investigation.status == status]
        items = await self.session.scalars(
            select(Investigation)
            .where(*conditions)
            .order_by(Investigation.created_at.desc(), Investigation.id)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(Investigation).where(*conditions)
        )
        return list(items), total or 0

    async def update(
        self,
        investigation_id: uuid.UUID,
        *,
        title: str | None = None,
        description: str | None = None,
        clear_description: bool = False,
        status: InvestigationStatus | None = None,
    ) -> Investigation:
        """Change the given fields. A closed investigation must be reopened in the same call."""
        investigation = await self._locked(investigation_id)
        if status is not None:
            investigation.status = status
        changes_details = title is not None or description is not None or clear_description
        if changes_details and investigation.status is InvestigationStatus.CLOSED:
            await self.session.rollback()
            raise ConflictError(CLOSED_ERROR)
        if title is not None:
            investigation.title = title
        if description is not None or clear_description:
            investigation.description = description
        await self._commit()
        return investigation

    async def close(self, investigation_id: uuid.UUID) -> Investigation:
        return await self.update(investigation_id, status=InvestigationStatus.CLOSED)

    async def reopen(self, investigation_id: uuid.UUID) -> Investigation:
        return await self.update(investigation_id, status=InvestigationStatus.OPEN)

    async def delete(self, investigation_id: uuid.UUID) -> None:
        """Delete an open investigation and its items. The saved records stay."""
        investigation = await self._open(investigation_id)
        await self.session.delete(investigation)
        await self._commit()

    async def add_item(
        self,
        investigation_id: uuid.UUID,
        item_type: InvestigationItemType,
        reference_id: uuid.UUID,
        label: str | None = None,
    ) -> InvestigationItem:
        """Save a reference to an existing record, with a snapshot of it now."""
        await self._open(investigation_id)
        snapshot = await SNAPSHOT_READERS[item_type](self.session, reference_id)
        if snapshot is None:
            await self.session.rollback()
            raise NotFoundError(f"The {item_type.value.replace('_', ' ')} to save was not found.")
        item = InvestigationItem(
            investigation_id=investigation_id,
            item_type=item_type,
            reference_id=reference_id,
            label=label,
            snapshot=snapshot,
        )
        self.session.add(item)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            if is_unique_violation(error):
                raise ConflictError("This item is already saved in the investigation.") from error
            raise
        except Exception:
            await self.session.rollback()
            raise
        return item

    async def save_research_session(
        self, investigation_id: uuid.UUID, session_id: uuid.UUID
    ) -> tuple[InvestigationItem, bool]:
        """Save a research session in an investigation, once.

        Returns the item and whether it was saved now. Saving the same session
        again returns the item saved before, with its first snapshot.
        """
        await self._open(investigation_id)
        existing = await self.session.scalar(
            select(InvestigationItem).where(
                InvestigationItem.investigation_id == investigation_id,
                InvestigationItem.item_type == InvestigationItemType.RESEARCH_SESSION,
                InvestigationItem.reference_id == session_id,
            )
        )
        if existing is not None:
            await self.session.rollback()
            return existing, False
        # The investigation row stays locked, so a second save waits and then
        # finds this item instead of adding another.
        item = await self.add_item(
            investigation_id, InvestigationItemType.RESEARCH_SESSION, session_id
        )
        return item, True

    async def remove_item(self, investigation_id: uuid.UUID, item_id: uuid.UUID) -> None:
        await self._open(investigation_id)
        item = await self.session.get(InvestigationItem, item_id)
        if item is None or item.investigation_id != investigation_id:
            await self.session.rollback()
            raise NotFoundError("Investigation item was not found.")
        await self.session.delete(item)
        await self._commit()

    async def list_items(self, investigation_id: uuid.UUID) -> list[InvestigationItem]:
        """The items of an investigation, in the order they were saved."""
        await self.get(investigation_id)
        items = await self.session.scalars(
            select(InvestigationItem)
            .where(InvestigationItem.investigation_id == investigation_id)
            .order_by(InvestigationItem.created_at, InvestigationItem.id)
        )
        return list(items)

    async def _locked(self, investigation_id: uuid.UUID) -> Investigation:
        investigation = await self.session.get(
            Investigation, investigation_id, with_for_update=True, populate_existing=True
        )
        if investigation is None:
            await self.session.rollback()
            raise NotFoundError("Investigation was not found.")
        return investigation

    async def _open(self, investigation_id: uuid.UUID) -> Investigation:
        # The lock keeps the investigation from being closed while it changes.
        investigation = await self._locked(investigation_id)
        if investigation.status is InvestigationStatus.CLOSED:
            await self.session.rollback()
            raise ConflictError(CLOSED_ERROR)
        return investigation

    async def _commit(self) -> None:
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise


def _time(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


async def _source(session: AsyncSession, reference_id: uuid.UUID) -> dict[str, Any] | None:
    source = await session.get(Source, reference_id)
    if source is None:
        return None
    return {"name": source.name, "source_type": source.type.value, "url": source.url}


async def _document(session: AsyncSession, reference_id: uuid.UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(Document.title, Document.url, Document.published_at, Document.source_id).where(
                Document.id == reference_id
            )
        )
    ).one_or_none()
    if row is None:
        return None
    title, url, published_at, source_id = row
    return {
        "title": title,
        "url": url,
        "published_at": _time(published_at),
        "source_id": str(source_id),
    }


async def _event(session: AsyncSession, reference_id: uuid.UUID) -> dict[str, Any] | None:
    event = await session.get(Event, reference_id)
    if event is None:
        return None
    return {
        "event_type": event.event_type,
        "title": event.title,
        "occurred_at": _time(event.occurred_at),
    }


async def _event_cluster(session: AsyncSession, reference_id: uuid.UUID) -> dict[str, Any] | None:
    cluster = await session.get(EventCluster, reference_id)
    if cluster is None:
        return None
    return {
        "event_type": cluster.event_type,
        "title": cluster.canonical_title,
        "occurred_at": _time(cluster.occurred_at),
    }


async def _entity(session: AsyncSession, reference_id: uuid.UUID) -> dict[str, Any] | None:
    entity = await session.get(Entity, reference_id)
    if entity is None:
        return None
    return {"canonical_name": entity.canonical_name, "entity_type": entity.entity_type}


async def _claim(session: AsyncSession, reference_id: uuid.UUID) -> dict[str, Any] | None:
    claim = await session.get(Claim, reference_id)
    if claim is None:
        return None
    return {"text": claim.text, "claim_type": claim.claim_type}


async def _research_session(
    session: AsyncSession, reference_id: uuid.UUID
) -> dict[str, Any] | None:
    research = await session.get(ResearchSession, reference_id)
    if research is None:
        return None
    turn_count, latest_turn_at = (
        await session.execute(
            select(func.count(), func.max(ResearchTurn.created_at)).where(
                ResearchTurn.session_id == reference_id
            )
        )
    ).one()
    return {
        "title": research.title,
        "retrieval_mode": research.retrieval_mode.value,
        "source_id": None if research.source_id is None else str(research.source_id),
        "turn_count": turn_count,
        "latest_turn_at": _time(latest_turn_at),
    }


SNAPSHOT_READERS: dict[InvestigationItemType, SnapshotReader] = {
    InvestigationItemType.SOURCE: _source,
    InvestigationItemType.DOCUMENT: _document,
    InvestigationItemType.EVENT: _event,
    InvestigationItemType.EVENT_CLUSTER: _event_cluster,
    InvestigationItemType.ENTITY: _entity,
    InvestigationItemType.CLAIM: _claim,
    InvestigationItemType.RESEARCH_SESSION: _research_session,
}
