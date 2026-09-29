from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.investigations.model import Investigation, InvestigationStatus


def test_investigations_table() -> None:
    sql = str(CreateTable(Investigation.__table__).compile(dialect=postgresql.dialect()))

    for column in [
        "title VARCHAR(200) NOT NULL",
        "description TEXT,",
        "status VARCHAR(20) NOT NULL",
        "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
        "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
    ]:
        assert column in sql
    assert "CHECK (btrim(title) <> '')" in sql
    assert "CHECK (status IN ('open', 'closed'))" in sql
    assert Base.metadata.tables["investigations"] is Investigation.__table__


def test_open_is_the_default_status() -> None:
    column = Investigation.__table__.c.status
    assert column.default.arg is InvestigationStatus.OPEN  # type: ignore[union-attr]


def test_ownership_columns() -> None:
    sql = str(CreateTable(Investigation.__table__).compile(dialect=postgresql.dialect()))

    # Both are optional, because legacy investigations have neither.
    assert "organization_id UUID," in sql
    assert "created_by_user_id UUID," in sql
    assert "FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE RESTRICT" in sql
    assert "FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE RESTRICT" in sql
    assert {index.name for index in Investigation.__table__.indexes} == {
        "ix_investigations_organization_id"
    }


def test_collaborators_table() -> None:
    from signalscope.domain.investigations.collaborator import (
        CollaboratorRole,
        InvestigationCollaborator,
    )

    sql = str(
        CreateTable(InvestigationCollaborator.__table__).compile(dialect=postgresql.dialect())
    )

    assert "PRIMARY KEY (investigation_id, user_id)" in sql
    assert "REFERENCES investigations (id) ON DELETE CASCADE" in sql
    assert "REFERENCES users (id) ON DELETE RESTRICT" in sql
    assert "CHECK (role IN ('owner', 'editor', 'viewer'))" in sql
    assert [role.value for role in CollaboratorRole] == ["owner", "editor", "viewer"]
