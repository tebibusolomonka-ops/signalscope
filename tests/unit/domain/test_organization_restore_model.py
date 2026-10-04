from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.domain.organizations.restore_record import OrganizationRestore


def table_sql() -> str:
    return str(CreateTable(OrganizationRestore.__table__).compile(dialect=postgresql.dialect()))


def test_restore_table_keeps_safe_lifecycle_metadata() -> None:
    sql = table_sql()

    assert "source_export_sha256 VARCHAR(64) NOT NULL" in sql
    assert "status VARCHAR(20) NOT NULL" in sql
    assert "summary JSONB DEFAULT '{}'::jsonb NOT NULL" in sql
    assert "organization_restore_status" in sql
    assert "CHECK (status IN ('planned', 'running', 'completed', 'failed'))" in sql


def test_restore_table_does_not_store_archive_binary() -> None:
    columns = OrganizationRestore.__table__.columns

    assert "archive" not in columns
    assert "artifact_key" not in columns
    assert "source_export_sha256" in columns
