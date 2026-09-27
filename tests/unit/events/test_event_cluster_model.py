import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.events.cluster import (
    EventCluster,
    EventClusterMember,
    normalize_event_title,
)


def sql_of(table: object) -> str:
    return str(CreateTable(table).compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


def test_event_clusters_table() -> None:
    sql = sql_of(EventCluster.__table__)

    for column in [
        "event_type VARCHAR(50) NOT NULL",
        "canonical_title VARCHAR(500) NOT NULL",
        "normalized_title VARCHAR(500) NOT NULL",
        "occurred_at TIMESTAMP WITH TIME ZONE,",
    ]:
        assert column in sql
    indexes = {index.name for index in EventCluster.__table__.indexes}
    assert indexes == {"ix_event_clusters_event_type_normalized_title"}
    assert Base.metadata.tables["event_clusters"] is EventCluster.__table__


def test_event_cluster_members_table() -> None:
    sql = sql_of(EventClusterMember.__table__)

    # The event is the key, so one event is in at most one cluster.
    assert "PRIMARY KEY (event_id)" in sql
    assert "FOREIGN KEY(event_id) REFERENCES events (id) ON DELETE CASCADE" in sql
    assert "FOREIGN KEY(cluster_id) REFERENCES event_clusters (id) ON DELETE CASCADE" in sql
    assert "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in sql
    indexes = {index.name for index in EventClusterMember.__table__.indexes}
    assert indexes == {"ix_event_cluster_members_cluster_id"}
    assert Base.metadata.tables["event_cluster_members"] is EventClusterMember.__table__


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("  River  Flood\tin\nPorto ", "river flood in porto"),
        ("STRASSE Flood", "strasse flood"),
        ("Straße flood", "strasse flood"),
        ("ｆｌｏｏｄ", "flood"),
        ("Flood 2024!", "flood 2024!"),
        ("Election, round 2", "election, round 2"),
    ],
    ids=["spaces", "upper case", "case folding", "width", "numbers", "punctuation"],
)
def test_normalize_event_title(title: str, expected: str) -> None:
    assert normalize_event_title(title) == expected


def test_different_numbers_stay_different() -> None:
    assert normalize_event_title("Flood 2024") != normalize_event_title("Flood 2025")
