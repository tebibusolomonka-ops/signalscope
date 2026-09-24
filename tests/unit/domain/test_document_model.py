from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.domain.documents.model import Document


def test_documents_table() -> None:
    sql = str(CreateTable(Document.__table__).compile(dialect=postgresql.dialect()))

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
    sql = str(CreateTable(Document.__table__).compile(dialect=postgresql.dialect()))

    assert (
        "CONSTRAINT fk_documents_source_id_sources FOREIGN KEY(source_id) "
        "REFERENCES sources (id) ON DELETE RESTRICT" in sql
    )


def test_external_id_is_unique_per_source() -> None:
    sql = str(CreateTable(Document.__table__).compile(dialect=postgresql.dialect()))

    assert "CONSTRAINT uq_documents_source_id_external_id UNIQUE (source_id, external_id)" in sql
