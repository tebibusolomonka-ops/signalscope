import uuid

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.core.errors import NotFoundError
from signalscope.domain.claims.model import Claim
from signalscope.domain.events.model import Event
from signalscope.domain.investigations.export import (
    InvestigationExportService,
    investigation_markdown,
)
from signalscope.domain.investigations.item import InvestigationItemType
from signalscope.domain.investigations.service import InvestigationService

pytestmark = pytest.mark.anyio


async def test_export_keeps_snapshots_and_groups_items(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, "Wire")
    event = await report_event(session_factory, source, "Harbour flood")
    async with session_factory() as session:
        claim = Claim(text="Prices rose", normalized_text="prices rose", claim_type="statistic")
        session.add(claim)
        await session.commit()
        service = InvestigationService(session)
        investigation = await service.create("Harbour floods")
        # Saved in a different order than the export groups them.
        await service.add_item(investigation.id, InvestigationItemType.CLAIM, claim.id)
        await service.add_item(investigation.id, InvestigationItemType.EVENT, event, "Key")
        await service.add_item(investigation.id, InvestigationItemType.SOURCE, source)
    # The live event changes and the claim goes away after they were saved.
    async with session_factory() as session:
        await session.execute(update(Event).values(title="Renamed flood"))
        await session.execute(delete(Claim))
        await session.commit()

    async with session_factory() as session:
        export = await InvestigationExportService(session).export(investigation.id)

    assert [item.item_type for item in export.items] == [
        InvestigationItemType.SOURCE,
        InvestigationItemType.EVENT,
        InvestigationItemType.CLAIM,
    ]
    source_item, event_item, claim_item = export.items
    assert event_item.snapshot["title"] == "Harbour flood"
    assert (event_item.label, event_item.current_reference_exists) == ("Key", True)
    assert claim_item.snapshot["text"] == "Prices rose"
    assert claim_item.current_reference_exists is False
    assert source_item.current_reference_exists is True
    text = investigation_markdown(export)
    assert "Harbour flood (flood, date unknown). Note: Key." in text
    assert "Renamed" not in text
    assert '"Prices rose" (statistic). The record no longer exists.' in text


async def test_empty_and_unknown(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        investigation = await InvestigationService(session).create("Empty")
        export = await InvestigationExportService(session).export(investigation.id)
        with pytest.raises(NotFoundError):
            await InvestigationExportService(session).export(uuid.uuid4())

    assert export.items == []
    assert investigation_markdown(export).endswith("No saved items.\n")
