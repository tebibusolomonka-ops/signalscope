from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.documents.asset import DocumentAsset


def table_sql() -> str:
    return str(CreateTable(DocumentAsset.__table__).compile(dialect=postgresql.dialect()))


def test_document_assets_table() -> None:
    sql = table_sql()

    assert "document_id UUID NOT NULL" in sql
    assert "storage_key VARCHAR(255) NOT NULL" in sql
    assert "filename VARCHAR(255)," in sql
    assert "content_type VARCHAR(255) NOT NULL" in sql
    assert "size_bytes BIGINT NOT NULL" in sql
    assert "sha256 VARCHAR(64) NOT NULL" in sql


def test_a_document_has_at_most_one_asset() -> None:
    assert "CONSTRAINT uq_document_assets_document_id UNIQUE (document_id)" in table_sql()


def test_storage_keys_are_unique() -> None:
    assert "CONSTRAINT uq_document_assets_storage_key UNIQUE (storage_key)" in table_sql()


def test_checks() -> None:
    sql = table_sql()

    assert "CONSTRAINT ck_document_assets_size_bytes_not_negative CHECK (size_bytes >= 0)" in sql
    assert "CONSTRAINT ck_document_assets_sha256_is_hex CHECK (sha256 ~ '^[0-9a-f]{64}$')" in sql


def test_asset_references_document_without_cascade_delete() -> None:
    assert (
        "CONSTRAINT fk_document_assets_document_id_documents FOREIGN KEY(document_id) "
        "REFERENCES documents (id) ON DELETE RESTRICT"
    ) in table_sql()


def test_asset_is_in_project_metadata() -> None:
    assert Base.metadata.tables["document_assets"] is DocumentAsset.__table__
