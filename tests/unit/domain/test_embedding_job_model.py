from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from signalscope.db.models import Base
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus

DIALECT = postgresql.dialect()


def table_sql() -> str:
    return str(CreateTable(EmbeddingJob.__table__).compile(dialect=DIALECT))


def test_embedding_jobs_table() -> None:
    sql = table_sql()

    for column in [
        "chunk_id UUID NOT NULL",
        "provider VARCHAR(50) NOT NULL",
        "model VARCHAR(100) NOT NULL",
        "status VARCHAR(20) NOT NULL",
        "available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
        "claimed_at TIMESTAMP WITH TIME ZONE,",
        "heartbeat_at TIMESTAMP WITH TIME ZONE,",
        "lease_expires_at TIMESTAMP WITH TIME ZONE,",
        "finished_at TIMESTAMP WITH TIME ZONE,",
        "attempt_count INTEGER DEFAULT 0 NOT NULL",
        "last_error VARCHAR(1000),",
    ]:
        assert column in sql
    assert "CHECK (status IN ('pending', 'running', 'completed', 'failed'))" in sql
    assert "CHECK (attempt_count >= 0)" in sql


def test_one_job_per_chunk_provider_and_model() -> None:
    assert (
        "CONSTRAINT uq_embedding_jobs_chunk_id_provider_model UNIQUE (chunk_id, provider, model)"
    ) in table_sql()


def test_jobs_are_deleted_with_their_chunk() -> None:
    assert "FOREIGN KEY(chunk_id) REFERENCES document_chunks (id) ON DELETE CASCADE" in table_sql()


def test_indexes() -> None:
    indexes = {
        str(CreateIndex(index).compile(dialect=DIALECT)) for index in EmbeddingJob.__table__.indexes
    }

    assert indexes == {
        "CREATE INDEX ix_embedding_jobs_status_available_at "
        "ON embedding_jobs (status, available_at)"
    }


def test_defaults() -> None:
    columns = EmbeddingJob.__table__.c

    assert columns.status.default.arg is EmbeddingJobStatus.PENDING  # type: ignore[union-attr]
    assert columns.attempt_count.default.arg == 0  # type: ignore[union-attr]


def test_job_is_in_project_metadata() -> None:
    assert Base.metadata.tables["embedding_jobs"] is EmbeddingJob.__table__
