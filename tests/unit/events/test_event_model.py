from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.events.model import Event, EventEvidence


def sql_of(table: object) -> str:
    return str(CreateTable(table).compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


def test_events_table() -> None:
    sql = sql_of(Event.__table__)

    for column in [
        "event_type VARCHAR(50) NOT NULL",
        "title VARCHAR(500) NOT NULL",
        "summary TEXT,",
        "occurred_at TIMESTAMP WITH TIME ZONE,",
    ]:
        assert column in sql
    assert Base.metadata.tables["events"] is Event.__table__


def test_event_evidence_table() -> None:
    sql = sql_of(EventEvidence.__table__)

    assert "UNIQUE (event_id, chunk_id, provider, model)" in sql
    assert "FOREIGN KEY(event_id) REFERENCES events (id) ON DELETE CASCADE" in sql
    assert "FOREIGN KEY(chunk_id) REFERENCES document_chunks (id) ON DELETE CASCADE" in sql
    assert "CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))" in sql
    assert "metadata JSONB DEFAULT '{}'::jsonb NOT NULL" in sql
    assert Base.metadata.tables["event_evidence"] is EventEvidence.__table__
