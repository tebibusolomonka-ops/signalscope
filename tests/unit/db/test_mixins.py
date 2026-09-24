from sqlalchemy import String, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import CreateTable
from sqlalchemy.sql import ClauseElement

from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


# A separate base keeps this example table out of the project metadata.
class ExampleBase(DeclarativeBase):
    pass


class Example(UUIDPrimaryKeyMixin, TimestampMixin, ExampleBase):
    __tablename__ = "examples"

    name: Mapped[str] = mapped_column(String(50))


def compile_sql(statement: ClauseElement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_table_uses_uuid_key_and_utc_timestamps() -> None:
    sql = compile_sql(CreateTable(Example.__table__))

    assert "id UUID NOT NULL" in sql
    assert "PRIMARY KEY (id)" in sql
    assert "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in sql
    assert "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in sql


def test_update_sets_updated_at() -> None:
    sql = compile_sql(update(Example).values(name="changed"))

    assert "updated_at=now()" in sql
