from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.investigations.item import InvestigationItem, InvestigationItemType


def test_investigation_items_table() -> None:
    sql = str(CreateTable(InvestigationItem.__table__).compile(dialect=postgresql.dialect()))

    assert "UNIQUE (investigation_id, item_type, reference_id)" in sql
    assert "snapshot JSONB DEFAULT '{}'::jsonb NOT NULL" in sql
    assert "CHECK (jsonb_typeof(snapshot) = 'object')" in sql
    assert "FOREIGN KEY(investigation_id) REFERENCES investigations (id) ON DELETE CASCADE" in sql
    # A reference can point at several tables, so it has no foreign key.
    assert "REFERENCES" not in sql.split("reference_id", 1)[1].split(",", 1)[0]
    assert sql.count("REFERENCES") == 1
    # Items are history, so there is no updated_at.
    assert "updated_at" not in sql
    assert Base.metadata.tables["investigation_items"] is InvestigationItem.__table__


def test_item_types() -> None:
    assert [item.value for item in InvestigationItemType] == [
        "source",
        "document",
        "event",
        "event_cluster",
        "entity",
        "claim",
        "research_session",
    ]
    sql = str(CreateTable(InvestigationItem.__table__).compile(dialect=postgresql.dialect()))
    assert (
        "CHECK (item_type IN ('source', 'document', 'event', 'event_cluster', 'entity', "
        "'claim', 'research_session'))" in sql
    )
