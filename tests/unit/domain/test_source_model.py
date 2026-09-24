from sqlalchemy import insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.sources.model import Source, SourceType

DIALECT = postgresql.dialect()


def test_sources_table() -> None:
    sql = str(CreateTable(Source.__table__).compile(dialect=DIALECT))

    assert "type VARCHAR(20) NOT NULL" in sql
    assert "name VARCHAR(200) NOT NULL" in sql
    assert "url TEXT," in sql
    assert (
        "CONSTRAINT ck_sources_source_type CHECK (type IN ('web', 'rss', 'upload', 'api'))" in sql
    )


def test_source_type_is_stored_as_its_value() -> None:
    statement = insert(Source).values(type=SourceType.UPLOAD, name="Manual uploads")

    sql = str(statement.compile(dialect=DIALECT, compile_kwargs={"literal_binds": True}))

    assert "'upload'" in sql
    assert "'UPLOAD'" not in sql


def test_source_is_in_project_metadata() -> None:
    assert Base.metadata.tables["sources"] is Source.__table__
