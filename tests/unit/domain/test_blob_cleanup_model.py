from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.blobs.model import BlobCleanupTask


def table_sql() -> str:
    return str(CreateTable(BlobCleanupTask.__table__).compile(dialect=postgresql.dialect()))


def test_blob_cleanup_tasks_table() -> None:
    sql = table_sql()

    assert "storage_key VARCHAR(255) NOT NULL" in sql
    assert "attempt_count INTEGER DEFAULT 0 NOT NULL" in sql
    assert "available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in sql
    assert "last_error VARCHAR(1000)," in sql
    assert "CONSTRAINT uq_blob_cleanup_tasks_storage_key UNIQUE (storage_key)" in sql
    assert "CHECK (attempt_count >= 0)" in sql


def test_task_is_in_project_metadata() -> None:
    assert Base.metadata.tables["blob_cleanup_tasks"] is BlobCleanupTask.__table__
