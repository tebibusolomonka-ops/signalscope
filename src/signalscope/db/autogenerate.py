"""Settings for comparing the models with the database, as autogenerate does."""

from typing import Any

from signalscope.domain.search.embedding_model import E5_HNSW_INDEX_NAME

# Alembic cannot compare the cast in these index expressions, so it would
# report them as changed every time. Tests check their definitions instead.
UNCOMPARED_INDEXES = frozenset({E5_HNSW_INDEX_NAME})


def include_object(
    item: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    return not (type_ == "index" and name in UNCOMPARED_INDEXES)
