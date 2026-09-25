from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from signalscope.domain.documents.model import Document


def table_sql() -> str:
    return str(CreateTable(Document.__table__).compile(dialect=postgresql.dialect()))


def test_documents_table() -> None:
    sql = table_sql()

    assert "source_id UUID NOT NULL" in sql
    for optional_column in [
        "external_id VARCHAR(500),",
        "title TEXT,",
        "content TEXT,",
        "language VARCHAR(35),",
        "published_at TIMESTAMP WITH TIME ZONE,",
    ]:
        assert optional_column in sql


def test_document_references_source_without_cascade_delete() -> None:
    sql = table_sql()

    assert (
        "CONSTRAINT fk_documents_source_id_sources FOREIGN KEY(source_id) "
        "REFERENCES sources (id) ON DELETE RESTRICT" in sql
    )


def test_external_id_is_unique_per_source() -> None:
    sql = table_sql()

    assert "CONSTRAINT uq_documents_source_id_external_id UNIQUE (source_id, external_id)" in sql


def test_url_is_optional_and_indexed_with_source() -> None:
    [index] = Document.__table__.indexes

    assert "url VARCHAR(2048)," in table_sql()
    assert str(CreateIndex(index).compile(dialect=postgresql.dialect())) == (
        "CREATE INDEX ix_documents_source_id_url ON documents (source_id, url)"
    )


def test_content_hash_is_unique_per_source() -> None:
    sql = table_sql()

    assert "content_hash VARCHAR(64)," in sql
    assert "CONSTRAINT uq_documents_source_id_content_hash UNIQUE (source_id, content_hash)" in sql
