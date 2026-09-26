from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from signalscope.db.models import Base
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus

DIALECT = postgresql.dialect()


def table_sql() -> str:
    return str(CreateTable(DocumentProcessingJob.__table__).compile(dialect=DIALECT))


def test_document_processing_jobs_table() -> None:
    sql = table_sql()

    assert "document_id UUID NOT NULL" in sql
    assert "asset_id UUID NOT NULL" in sql
    assert "status VARCHAR(20) NOT NULL" in sql
    assert "available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in sql
    assert "claimed_at TIMESTAMP WITH TIME ZONE," in sql
    assert "heartbeat_at TIMESTAMP WITH TIME ZONE," in sql
    assert "lease_expires_at TIMESTAMP WITH TIME ZONE," in sql
    assert "finished_at TIMESTAMP WITH TIME ZONE," in sql
    assert "attempt_count INTEGER DEFAULT 0 NOT NULL" in sql
    assert "last_error VARCHAR(1000)," in sql
    assert "CHECK (status IN ('pending', 'running', 'completed', 'failed'))" in sql
    assert "CHECK (attempt_count >= 0)" in sql


def test_one_job_per_asset() -> None:
    assert "CONSTRAINT uq_document_processing_jobs_asset_id UNIQUE (asset_id)" in table_sql()


def test_foreign_keys_restrict_deletes() -> None:
    sql = table_sql()

    assert "FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE RESTRICT" in sql
    assert "FOREIGN KEY(asset_id) REFERENCES document_assets (id) ON DELETE RESTRICT" in sql


def test_indexes() -> None:
    indexes = {
        str(CreateIndex(index).compile(dialect=DIALECT))
        for index in DocumentProcessingJob.__table__.indexes
    }

    assert indexes == {
        "CREATE INDEX ix_document_processing_jobs_status_available_at "
        "ON document_processing_jobs (status, available_at)",
        "CREATE INDEX ix_document_processing_jobs_document_id "
        "ON document_processing_jobs (document_id)",
    }


def test_defaults() -> None:
    columns = DocumentProcessingJob.__table__.c

    assert columns.status.default.arg is ProcessingJobStatus.PENDING  # type: ignore[union-attr]
    assert columns.attempt_count.default.arg == 0  # type: ignore[union-attr]


def test_job_is_in_project_metadata() -> None:
    assert Base.metadata.tables["document_processing_jobs"] is DocumentProcessingJob.__table__
