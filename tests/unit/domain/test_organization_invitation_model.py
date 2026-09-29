import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.core.settings import Settings, SettingsError, load_settings
from signalscope.domain.organizations.invitation import InvitationRole, OrganizationInvitation


def test_table() -> None:
    table = OrganizationInvitation.__table__
    sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))

    assert "CHECK (role IN ('admin', 'member', 'viewer'))" in sql
    assert "owner" not in sql
    assert "token_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "UNIQUE (token_hash)" in sql
    assert "expires_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql
    assert "REFERENCES organizations (id) ON DELETE CASCADE" in sql
    assert "REFERENCES users (id) ON DELETE RESTRICT" in sql
    assert {index.name for index in table.indexes} == {
        "ix_organization_invitations_organization_id",
        "ix_organization_invitations_normalized_email",
        "ix_organization_invitations_expires_at",
    }
    # History rows stay, so an email may have many invitations.
    unique = [c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"]
    assert [[column.name for column in c.columns] for c in unique] == [["token_hash"]]


def test_no_owner_role() -> None:
    assert [role.value for role in InvitationRole] == ["admin", "member", "viewer"]


def test_setting() -> None:
    assert Settings().organization_invitation_days == 7
    found = load_settings({"SIGNALSCOPE_ORGANIZATION_INVITATION_DAYS": "30"})
    assert found.organization_invitation_days == 30


@pytest.mark.parametrize("days", ["0", "91"])
def test_setting_bounds(days: str) -> None:
    with pytest.raises(SettingsError, match="organization_invitation_days"):
        load_settings({"SIGNALSCOPE_ORGANIZATION_INVITATION_DAYS": days})
