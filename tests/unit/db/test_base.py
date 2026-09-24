from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from signalscope.db.base import Base


def test_constraint_names_follow_naming_convention() -> None:
    # A separate MetaData keeps these example tables out of the project metadata.
    metadata = MetaData(naming_convention=Base.metadata.naming_convention)
    Table("parent", metadata, Column("id", Integer, primary_key=True))
    child = Table(
        "child",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, unique=True),
        Column("parent_id", ForeignKey("parent.id"), index=True),
    )
    dialect = postgresql.dialect()

    table_sql = str(CreateTable(child).compile(dialect=dialect))
    index_sql = "".join(str(CreateIndex(index).compile(dialect=dialect)) for index in child.indexes)

    assert "CONSTRAINT pk_child " in table_sql
    assert "CONSTRAINT uq_child_name " in table_sql
    assert "CONSTRAINT fk_child_parent_id_parent " in table_sql
    assert "CREATE INDEX ix_child_parent_id " in index_sql
