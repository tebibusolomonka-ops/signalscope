from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.documents.revision import DocumentRevision


def table_sql() -> str:
    return str(CreateTable(DocumentRevision.__table__).compile(dialect=postgresql.dialect()))


def test_document_revisions_table() -> None:
    sql = table_sql()

    for column in [
        "document_id UUID NOT NULL",
        "version INTEGER NOT NULL",
        "title TEXT,",
        "content TEXT,",
        "language VARCHAR(35),",
        "url VARCHAR(2048),",
        "content_hash VARCHAR(64),",
        "metadata JSONB DEFAULT '{}'::jsonb NOT NULL",
        "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
    ]:
        assert column in sql
    # History is never changed, so there is no updated_at.
    assert "updated_at" not in sql


def test_versions() -> None:
    sql = table_sql()

    assert "CONSTRAINT ck_document_revisions_version_positive CHECK (version > 0)" in sql
    assert (
        "CONSTRAINT uq_document_revisions_document_id_version UNIQUE (document_id, version)"
    ) in sql


def test_revisions_go_with_their_document() -> None:
    assert "FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE" in table_sql()


def test_metadata_must_be_an_object() -> None:
    assert "CHECK (jsonb_typeof(metadata) = 'object')" in table_sql()


def test_revision_is_in_project_metadata() -> None:
    assert Base.metadata.tables["document_revisions"] is DocumentRevision.__table__
