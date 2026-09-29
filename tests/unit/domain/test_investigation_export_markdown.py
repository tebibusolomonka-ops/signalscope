import uuid
from datetime import UTC, datetime
from typing import Any

from signalscope.domain.investigations.export import (
    ExportedItem,
    InvestigationExport,
    investigation_markdown,
)
from signalscope.domain.investigations.item import InvestigationItemType
from signalscope.domain.investigations.model import InvestigationStatus
from signalscope.domain.investigations.schemas import InvestigationRead

SAVED = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


def investigation(description: str | None = None) -> InvestigationRead:
    return InvestigationRead(
        id=uuid.UUID(int=1),
        title="Harbour floods",
        description=description,
        status=InvestigationStatus.OPEN,
        organization_id=None,
        created_by_user_id=None,
        created_at=SAVED,
        updated_at=SAVED,
    )


def item(
    item_type: InvestigationItemType,
    snapshot: dict[str, Any],
    label: str | None = None,
    exists: bool = True,
) -> ExportedItem:
    return ExportedItem(
        id=uuid.uuid4(),
        item_type=item_type,
        reference_id=uuid.uuid4(),
        label=label,
        snapshot=snapshot,
        created_at=SAVED,
        current_reference_exists=exists,
    )


def test_empty_investigation() -> None:
    export = InvestigationExport(investigation=investigation("Notes."), items=[])

    assert investigation_markdown(export) == (
        "# Harbour floods\n\nStatus: open\n\nNotes.\n\nNo saved items.\n"
    )


def test_items_are_grouped_and_described_from_snapshots() -> None:
    export = InvestigationExport(
        investigation=investigation(),
        items=[
            item(InvestigationItemType.SOURCE, {"name": "Wire", "source_type": "rss"}),
            item(
                InvestigationItemType.DOCUMENT,
                {"title": None, "url": "https://example.org/a", "published_at": "2026-03-04"},
            ),
            item(
                InvestigationItemType.EVENT,
                {"title": "Harbour flood", "event_type": "flood", "occurred_at": None},
                label="Key event",
            ),
            item(
                InvestigationItemType.EVENT_CLUSTER,
                {"title": "Harbour flood", "event_type": "flood", "occurred_at": "2026-03-04"},
            ),
            item(InvestigationItemType.ENTITY, {"canonical_name": "Porto", "entity_type": "city"}),
            item(
                InvestigationItemType.CLAIM,
                {"text": "Prices rose 5%", "claim_type": "statistic"},
                exists=False,
            ),
            item(
                InvestigationItemType.RESEARCH_SESSION,
                {"title": None, "retrieval_mode": "hybrid", "turn_count": 2},
            ),
        ],
    )

    text = investigation_markdown(export)

    assert text == investigation_markdown(export)
    assert text == (
        "# Harbour floods\n\nStatus: open\n"
        "\n## Sources\n\n- Wire (rss). Saved 2026-03-04.\n"
        "\n## Documents\n\n"
        "- (no title) (https://example.org/a), published 2026-03-04. Saved 2026-03-04.\n"
        "\n## Events\n\n"
        "- Harbour flood (flood, date unknown). Note: Key event. Saved 2026-03-04.\n"
        "\n## Event clusters\n\n- Harbour flood (flood, 2026-03-04). Saved 2026-03-04.\n"
        "\n## Entities\n\n- Porto (city). Saved 2026-03-04.\n"
        "\n## Claims\n\n"
        '- "Prices rose 5%" (statistic). The record no longer exists. Saved 2026-03-04.\n'
        "\n## Research sessions\n\n- Research session (hybrid, 2 turns). Saved 2026-03-04.\n"
    )
