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
    # No owner: there are no users yet.
    assert "owner" not in sql and "user" not in sql
    assert Base.metadata.tables["investigations"] is Investigation.__table__


def test_open_is_the_default_status() -> None:
    column = Investigation.__table__.c.status
    assert column.default.arg is InvestigationStatus.OPEN  # type: ignore[union-attr]
