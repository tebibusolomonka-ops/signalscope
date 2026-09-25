from sqlalchemy import insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from signalscope.domain.ingestion.model import IngestionRun, IngestionStatus

DIALECT = postgresql.dialect()


def table_sql() -> str:
    return str(CreateTable(IngestionRun.__table__).compile(dialect=DIALECT))


def test_ingestion_runs_table() -> None:
    sql = table_sql()

    assert "source_id UUID NOT NULL" in sql
    assert "status VARCHAR(20) NOT NULL" in sql
    assert "started_at TIMESTAMP WITH TIME ZONE," in sql
    assert "finished_at TIMESTAMP WITH TIME ZONE," in sql
    assert "error_message VARCHAR(1000)," in sql
    assert (
        "CONSTRAINT ck_ingestion_runs_ingestion_status "
        "CHECK (status IN ('pending', 'running', 'completed', 'failed'))" in sql
    )


def test_run_references_source_without_cascade_delete() -> None:
    assert (
        "CONSTRAINT fk_ingestion_runs_source_id_sources FOREIGN KEY(source_id) "
        "REFERENCES sources (id) ON DELETE RESTRICT" in table_sql()
    )


def test_runs_are_indexed_by_source() -> None:
    [index] = IngestionRun.__table__.indexes

    assert str(CreateIndex(index).compile(dialect=DIALECT)) == (
        "CREATE INDEX ix_ingestion_runs_source_id ON ingestion_runs (source_id)"
    )


def test_status_is_stored_as_its_value() -> None:
    statement = insert(IngestionRun).values(status=IngestionStatus.RUNNING)

    sql = str(statement.compile(dialect=DIALECT, compile_kwargs={"literal_binds": True}))

    assert "'running'" in sql
    assert "'RUNNING'" not in sql


def test_new_runs_are_pending() -> None:
    default = IngestionRun.__table__.c.status.default

    assert default is not None
    assert default.arg is IngestionStatus.PENDING  # type: ignore[union-attr]


def test_counters_start_at_zero_and_cannot_go_negative() -> None:
    sql = table_sql()

    for counter in ["items_seen", "documents_created", "duplicates_skipped"]:
        assert f"{counter} INTEGER DEFAULT 0 NOT NULL" in sql
        assert f"CONSTRAINT ck_ingestion_runs_{counter}_not_negative CHECK ({counter} >= 0)" in sql
        assert IngestionRun.__table__.c[counter].default.arg == 0  # type: ignore[union-attr]
