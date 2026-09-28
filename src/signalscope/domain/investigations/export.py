import uuid
from collections import defaultdict
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.db.base import Base
from signalscope.domain.claims.model import Claim
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.cluster import EventCluster
from signalscope.domain.events.model import Event
from signalscope.domain.investigations.item import InvestigationItem, InvestigationItemType
from signalscope.domain.investigations.schemas import InvestigationItemRead, InvestigationRead
from signalscope.domain.investigations.service import InvestigationService
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.sources.model import Source

TABLES: dict[InvestigationItemType, type[Base]] = {
    InvestigationItemType.SOURCE: Source,
    InvestigationItemType.DOCUMENT: Document,
    InvestigationItemType.EVENT: Event,
    InvestigationItemType.EVENT_CLUSTER: EventCluster,
    InvestigationItemType.ENTITY: Entity,
    InvestigationItemType.CLAIM: Claim,
    InvestigationItemType.RESEARCH_SESSION: ResearchSession,
}

HEADINGS = {
    InvestigationItemType.SOURCE: "Sources",
    InvestigationItemType.DOCUMENT: "Documents",
    InvestigationItemType.EVENT: "Events",
    InvestigationItemType.EVENT_CLUSTER: "Event clusters",
    InvestigationItemType.ENTITY: "Entities",
    InvestigationItemType.CLAIM: "Claims",
    InvestigationItemType.RESEARCH_SESSION: "Research sessions",
}


class ExportedItem(InvestigationItemRead):
    # Whether the saved record still exists now. The snapshot is kept either way.
    current_reference_exists: bool


class InvestigationExport(BaseModel):
    investigation: InvestigationRead
    # Grouped by item type, in a fixed type order, then in the order saved.
    items: list[ExportedItem]


class InvestigationExportService:
    """Exports an investigation from the snapshots saved with its items.

    Snapshots are shown as they were saved and are never replaced with live
    data. The only live value is whether each record still exists.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def export(self, investigation_id: uuid.UUID) -> InvestigationExport:
        service = InvestigationService(self.session)
        investigation = await service.get(investigation_id)
        items = await service.list_items(investigation_id)
        existing = await self._existing(items)
        order = list(InvestigationItemType)
        items.sort(key=lambda item: (order.index(item.item_type), item.created_at, item.id))
        return InvestigationExport(
            investigation=InvestigationRead.model_validate(investigation),
            items=[
                ExportedItem(
                    **InvestigationItemRead.model_validate(item).model_dump(),
                    current_reference_exists=(item.item_type, item.reference_id) in existing,
                )
                for item in items
            ],
        )

    async def _existing(
        self, items: list[InvestigationItem]
    ) -> set[tuple[InvestigationItemType, uuid.UUID]]:
        """The saved references whose records still exist, one query per item type."""
        by_type: dict[InvestigationItemType, list[uuid.UUID]] = defaultdict(list)
        for item in items:
            by_type[item.item_type].append(item.reference_id)
        found: set[tuple[InvestigationItemType, uuid.UUID]] = set()
        for item_type, reference_ids in by_type.items():
            table = TABLES[item_type]
            ids = await self.session.scalars(
                select(table.id).where(table.id.in_(reference_ids))  # type: ignore[attr-defined]
            )
            found.update((item_type, reference_id) for reference_id in ids)
        return found


def investigation_markdown(export: InvestigationExport) -> str:
    """The export as a Markdown report. The same export always gives the same text."""
    investigation = export.investigation
    lines = [f"# {investigation.title}", "", f"Status: {investigation.status.value}"]
    if investigation.description:
        lines += ["", investigation.description]
    if not export.items:
        lines += ["", "No saved items."]
    current: InvestigationItemType | None = None
    for item in export.items:
        if item.item_type is not current:
            current = item.item_type
            lines += ["", f"## {HEADINGS[current]}", ""]
        line = f"- {_describe(item.item_type, item.snapshot)}"
        if item.label:
            line += f". Note: {item.label}"
        if not item.current_reference_exists:
            line += ". The record no longer exists"
        lines.append(f"{line}. Saved {item.created_at.date().isoformat()}.")
    return "\n".join(lines) + "\n"


def _describe(item_type: InvestigationItemType, snapshot: dict[str, Any]) -> str:
    """One line for a saved item, from its snapshot only."""
    match item_type:
        case InvestigationItemType.SOURCE:
            return f"{snapshot.get('name')} ({snapshot.get('source_type')})"
        case InvestigationItemType.DOCUMENT:
            text = snapshot.get("title") or "(no title)"
            if snapshot.get("url"):
                text += f" ({snapshot['url']})"
            if snapshot.get("published_at"):
                text += f", published {snapshot['published_at']}"
            return str(text)
        case InvestigationItemType.EVENT | InvestigationItemType.EVENT_CLUSTER:
            when = snapshot.get("occurred_at") or "date unknown"
            return f"{snapshot.get('title')} ({snapshot.get('event_type')}, {when})"
        case InvestigationItemType.ENTITY:
            return f"{snapshot.get('canonical_name')} ({snapshot.get('entity_type')})"
        case InvestigationItemType.CLAIM:
            return f'"{snapshot.get("text")}" ({snapshot.get("claim_type")})'
        case InvestigationItemType.RESEARCH_SESSION:
            title = snapshot.get("title") or "Research session"
            turns = snapshot.get("turn_count")
            count = "" if turns is None else f", {turns} turns"
            return f"{title} ({snapshot.get('retrieval_mode')}{count})"
