import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.entities.model import Entity
from signalscope.domain.entities.names import normalize_entity_name


def table_sql() -> str:
    return str(CreateTable(Entity.__table__).compile(dialect=postgresql.dialect()))


def test_entities_table() -> None:
    sql = table_sql()

    for column in [
        "canonical_name VARCHAR(300) NOT NULL",
        "normalized_name VARCHAR(300) NOT NULL",
        "entity_type VARCHAR(50) NOT NULL",
    ]:
        assert column in sql
    assert (
        "CONSTRAINT uq_entities_normalized_name_entity_type UNIQUE (normalized_name, entity_type)"
    ) in sql
    assert "CHECK (btrim(canonical_name) <> '')" in sql
    assert "CHECK (btrim(entity_type) <> '')" in sql


def test_entity_is_in_project_metadata() -> None:
    assert Base.metadata.tables["entities"] is Entity.__table__


@pytest.mark.parametrize(
    ("name", "normalized"),
    [
        ("Angela Merkel", "angela merkel"),
        ("  Angela \t\n Merkel  ", "angela merkel"),
        ("ÁNGELA MERKEL", "ángela merkel"),
        ("Straße", "strasse"),
        # Compatible forms, such as full-width letters, become plain ones.
        ("ＡＢＣ News", "abc news"),
        ("AT&T", "at&t"),
        ("O'Brien", "o'brien"),
        ("Jean-Luc Picard", "jean-luc picard"),
    ],
)
def test_normalize_entity_name(name: str, normalized: str) -> None:
    assert normalize_entity_name(name) == normalized


def test_normalizing_twice_changes_nothing() -> None:
    once = normalize_entity_name("  Ｍüller  AG ")

    assert normalize_entity_name(once) == once
