from sqlalchemy import insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.sources.model import MAX_INGESTION_INTERVAL_MINUTES, Source, SourceType

DIALECT = postgresql.dialect()


def test_sources_table() -> None:
    sql = str(CreateTable(Source.__table__).compile(dialect=DIALECT))

    assert "type VARCHAR(20) NOT NULL" in sql
    assert "name VARCHAR(200) NOT NULL" in sql
    assert "url TEXT," in sql
    assert (
        "CONSTRAINT ck_sources_source_type CHECK (type IN ('web', 'rss', 'upload', 'api'))" in sql
    )


def test_scheduling_columns() -> None:
    sql = str(CreateTable(Source.__table__).compile(dialect=DIALECT))

    assert "ingestion_enabled BOOLEAN DEFAULT false NOT NULL" in sql
    assert "ingestion_interval_minutes INTEGER," in sql
    assert "next_ingestion_at TIMESTAMP WITH TIME ZONE," in sql
    assert (
        "CONSTRAINT ck_sources_ingestion_interval_minutes_in_range "
        "CHECK (ingestion_interval_minutes BETWEEN 1 AND 10080)"
    ) in sql
    assert (
        "CONSTRAINT ck_sources_enabled_ingestion_has_interval "
        "CHECK (NOT ingestion_enabled OR ingestion_interval_minutes IS NOT NULL)"
    ) in sql


def test_ingestion_is_off_by_default() -> None:
    default = Source.__table__.c.ingestion_enabled.default

    assert default is not None
    assert default.arg is False  # type: ignore[union-attr]
    assert MAX_INGESTION_INTERVAL_MINUTES == 7 * 24 * 60


def test_source_type_is_stored_as_its_value() -> None:
    statement = insert(Source).values(type=SourceType.UPLOAD, name="Manual uploads")

    sql = str(statement.compile(dialect=DIALECT, compile_kwargs={"literal_binds": True}))

    assert "'upload'" in sql
    assert "'UPLOAD'" not in sql


def test_source_is_in_project_metadata() -> None:
    assert Base.metadata.tables["sources"] is Source.__table__
