from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.documents.chunk import DocumentChunk


def table_sql() -> str:
    return str(CreateTable(DocumentChunk.__table__).compile(dialect=postgresql.dialect()))


def test_document_chunks_table() -> None:
    sql = table_sql()

    for column in [
        "document_id UUID NOT NULL",
        "position INTEGER NOT NULL",
        "text TEXT NOT NULL",
        "start_char INTEGER NOT NULL",
        "end_char INTEGER NOT NULL",
        "text_hash VARCHAR(64) NOT NULL",
    ]:
        assert column in sql


def test_positions_are_unique_per_document() -> None:
    assert (
        "CONSTRAINT uq_document_chunks_document_id_position UNIQUE (document_id, position)"
        in table_sql()
    )


def test_checks() -> None:
    sql = table_sql()

    for check in [
        "CHECK (position >= 0)",
        "CHECK (start_char >= 0)",
        "CHECK (end_char >= start_char)",
        "CHECK (text <> '')",
        "CHECK (text_hash ~ '^[0-9a-f]{64}$')",
        "CHECK (jsonb_typeof(metadata) = 'object')",
    ]:
        assert check in sql


def test_chunks_are_deleted_with_their_document() -> None:
    assert (
        "CONSTRAINT fk_document_chunks_document_id_documents FOREIGN KEY(document_id) "
        "REFERENCES documents (id) ON DELETE CASCADE"
    ) in table_sql()


def test_chunk_is_in_project_metadata() -> None:
    assert Base.metadata.tables["document_chunks"] is DocumentChunk.__table__


def test_metadata_column() -> None:
    table = DocumentChunk.__table__

    assert "metadata JSONB DEFAULT '{}'::jsonb NOT NULL" in table_sql()
    assert DocumentChunk.__mapper__.c.chunk_metadata is table.c.metadata
