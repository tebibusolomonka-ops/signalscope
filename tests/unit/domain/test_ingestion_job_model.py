from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from signalscope.db.models import Base
from signalscope.domain.ingestion.model import IngestionJob, IngestionJobStatus

DIALECT = postgresql.dialect()


def table_sql() -> str:
    return str(CreateTable(IngestionJob.__table__).compile(dialect=DIALECT))


def test_ingestion_jobs_table() -> None:
    sql = table_sql()

    assert "source_id UUID NOT NULL" in sql
    assert "run_id UUID NOT NULL" in sql
    assert "status VARCHAR(20) NOT NULL" in sql
    assert "available_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql
    assert "claimed_at TIMESTAMP WITH TIME ZONE," in sql
    assert "finished_at TIMESTAMP WITH TIME ZONE," in sql
    assert "attempt_count INTEGER DEFAULT 0 NOT NULL" in sql
    assert "last_error VARCHAR(1000)," in sql
    assert (
        "CONSTRAINT ck_ingestion_jobs_ingestion_job_status "
        "CHECK (status IN ('pending', 'running', 'completed', 'failed'))"
    ) in sql
    assert (
        "CONSTRAINT ck_ingestion_jobs_attempt_count_not_negative CHECK (attempt_count >= 0)"
    ) in sql


def test_job_references_source_and_run_without_cascade_delete() -> None:
    sql = table_sql()

    assert (
        "CONSTRAINT fk_ingestion_jobs_source_id_sources FOREIGN KEY(source_id) "
        "REFERENCES sources (id) ON DELETE RESTRICT"
    ) in sql
    assert (
        "CONSTRAINT fk_ingestion_jobs_run_id_ingestion_runs FOREIGN KEY(run_id) "
        "REFERENCES ingestion_runs (id) ON DELETE RESTRICT"
    ) in sql


def test_a_run_has_at_most_one_job() -> None:
    assert "CONSTRAINT uq_ingestion_jobs_run_id UNIQUE (run_id)" in table_sql()


def test_indexes() -> None:
    indexes = {
        str(CreateIndex(index).compile(dialect=DIALECT)) for index in IngestionJob.__table__.indexes
    }

    assert indexes == {
        "CREATE INDEX ix_ingestion_jobs_status_available_at "
        "ON ingestion_jobs (status, available_at)",
        "CREATE INDEX ix_ingestion_jobs_source_id ON ingestion_jobs (source_id)",
    }


def test_defaults() -> None:
    columns = IngestionJob.__table__.c

    assert columns.status.default.arg is IngestionJobStatus.PENDING  # type: ignore[union-attr]
    assert columns.attempt_count.default.arg == 0  # type: ignore[union-attr]
    assert columns.available_at.default is None


def test_job_is_in_project_metadata() -> None:
    assert Base.metadata.tables["ingestion_jobs"] is IngestionJob.__table__
