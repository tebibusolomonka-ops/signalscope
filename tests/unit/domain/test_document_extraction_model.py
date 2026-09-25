from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from signalscope.db.models import Base
from signalscope.domain.documents.extraction import DocumentExtraction

DIALECT = postgresql.dialect()


def table_sql() -> str:
    return str(CreateTable(DocumentExtraction.__table__).compile(dialect=DIALECT))


def test_document_extractions_table() -> None:
    sql = table_sql()

    assert "document_id UUID NOT NULL" in sql
    assert "asset_id UUID NOT NULL" in sql
    assert "parser_name VARCHAR(100) NOT NULL" in sql
    assert "content_type VARCHAR(255) NOT NULL" in sql
    assert "metadata JSONB DEFAULT '{}'::jsonb NOT NULL" in sql
    assert "text_length INTEGER NOT NULL" in sql
    assert "processed_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql


def test_one_extraction_per_document() -> None:
    assert "CONSTRAINT uq_document_extractions_document_id UNIQUE (document_id)" in table_sql()


def test_checks() -> None:
    sql = table_sql()

    assert "CHECK (text_length >= 0)" in sql
    assert (
        "CONSTRAINT ck_document_extractions_metadata_is_object "
        "CHECK (jsonb_typeof(metadata) = 'object')"
    ) in sql


def test_foreign_keys_restrict_deletes() -> None:
    sql = table_sql()

    assert (
        "FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE RESTRICT" in sql
        and "FOREIGN KEY(asset_id) REFERENCES document_assets (id) ON DELETE RESTRICT" in sql
    )


def test_asset_id_is_indexed() -> None:
    [index] = DocumentExtraction.__table__.indexes

    assert str(CreateIndex(index).compile(dialect=DIALECT)) == (
        "CREATE INDEX ix_document_extractions_asset_id ON document_extractions (asset_id)"
    )


def test_metadata_attribute_maps_to_the_metadata_column() -> None:
    table = DocumentExtraction.__table__

    assert DocumentExtraction.__mapper__.c.parser_metadata is table.c.metadata
    assert Base.metadata.tables["document_extractions"] is table
