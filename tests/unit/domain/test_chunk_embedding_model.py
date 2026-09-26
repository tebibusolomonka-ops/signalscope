from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.search.embedding_model import ChunkEmbedding


def table_sql() -> str:
    return str(CreateTable(ChunkEmbedding.__table__).compile(dialect=postgresql.dialect()))


def test_chunk_embeddings_table() -> None:
    sql = table_sql()

    for column in [
        "chunk_id UUID NOT NULL",
        "provider VARCHAR(50) NOT NULL",
        "model VARCHAR(100) NOT NULL",
        "dimensions INTEGER NOT NULL",
        "chunk_text_hash VARCHAR(64) NOT NULL",
        "embedding VECTOR NOT NULL",
    ]:
        assert column in sql


def test_the_vector_size_is_not_fixed_yet() -> None:
    assert ChunkEmbedding.__table__.c.embedding.type.dim is None


def test_one_embedding_per_chunk_provider_and_model() -> None:
    assert (
        "CONSTRAINT uq_chunk_embeddings_chunk_id_provider_model UNIQUE (chunk_id, provider, model)"
    ) in table_sql()


def test_checks() -> None:
    sql = table_sql()

    assert "CHECK (dimensions > 0)" in sql
    assert "CHECK (chunk_text_hash ~ '^[0-9a-f]{64}$')" in sql


def test_embeddings_are_deleted_with_their_chunk() -> None:
    assert "FOREIGN KEY(chunk_id) REFERENCES document_chunks (id) ON DELETE CASCADE" in table_sql()


def test_embedding_is_in_project_metadata() -> None:
    assert Base.metadata.tables["chunk_embeddings"] is ChunkEmbedding.__table__
