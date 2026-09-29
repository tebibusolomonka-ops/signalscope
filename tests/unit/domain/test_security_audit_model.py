from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.domain.audit.model import SecurityAuditEvent


def test_table() -> None:
    table = SecurityAuditEvent.__table__
    sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))

    assert "metadata JSONB DEFAULT '{}'::jsonb NOT NULL" in sql
    assert "REFERENCES users (id) ON DELETE SET NULL" in sql
    assert "REFERENCES organizations (id) ON DELETE SET NULL" in sql
    assert "updated_at" not in sql
    assert {index.name for index in table.indexes} == {
        "ix_security_audit_events_actor_user_id",
        "ix_security_audit_events_organization_id",
        "ix_security_audit_events_action",
        "ix_security_audit_events_created_at",
    }
