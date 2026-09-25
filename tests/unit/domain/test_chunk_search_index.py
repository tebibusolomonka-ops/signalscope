from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from signalscope.domain.documents.chunk import (
    DocumentChunk,
    chunk_search_vector,
    text_search_config,
)

DIALECT = postgresql.dialect()


def test_search_index() -> None:
    [index] = [
        index
        for index in DocumentChunk.__table__.indexes
        if index.name == "ix_document_chunks_text_search"
    ]

    assert str(CreateIndex(index).compile(dialect=DIALECT)) == (
        "CREATE INDEX ix_document_chunks_text_search ON document_chunks "
        "USING gin (to_tsvector('simple'::regconfig, text))"
    )


def test_queries_repeat_the_index_expression() -> None:
    query = select(DocumentChunk.id).where(
        chunk_search_vector().bool_op("@@")(func.websearch_to_tsquery(text_search_config(), "x"))
    )

    sql = str(query.compile(dialect=DIALECT))

    # The configuration is written into the SQL, not sent as a parameter.
    assert "to_tsvector('simple'::regconfig, document_chunks.text)" in sql
    assert "websearch_to_tsquery('simple'::regconfig, " in sql
