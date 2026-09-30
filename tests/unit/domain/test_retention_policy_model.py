from signalscope.db.models import Base
from signalscope.domain.retention.model import (
    MAX_SECURITY_AUDIT_DAYS,
    MIN_SECURITY_AUDIT_DAYS,
    OrganizationRetentionPolicy,
)


def test_one_row_per_organization() -> None:
    table = OrganizationRetentionPolicy.__table__

    assert table.name in Base.metadata.tables
    assert [column.name for column in table.primary_key.columns] == ["organization_id"]
    assert [column.name for column in table.columns] == [
        "organization_id",
        "security_audit_days",
        "created_at",
        "updated_at",
    ]
    (foreign_key,) = table.c.organization_id.foreign_keys
    assert foreign_key.column.table.name == "organizations"
    assert foreign_key.ondelete == "CASCADE"


def test_audit_days_are_optional_and_bounded() -> None:
    table = OrganizationRetentionPolicy.__table__
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if constraint.name and "in_range" in str(constraint.name)
    }

    assert table.c.security_audit_days.nullable
    assert (MIN_SECURITY_AUDIT_DAYS, MAX_SECURITY_AUDIT_DAYS) == (30, 3650)
    assert list(checks.values()) == ["security_audit_days BETWEEN 30 AND 3650"]
