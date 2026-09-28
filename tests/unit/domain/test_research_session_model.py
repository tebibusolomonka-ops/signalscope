from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.research.session import ResearchSession
from signalscope.research.evidence import ResearchMode


def test_research_sessions_table() -> None:
    sql = str(CreateTable(ResearchSession.__table__).compile(dialect=postgresql.dialect()))

    for column in [
        "title VARCHAR(200),",
        "retrieval_mode VARCHAR(20) NOT NULL",
        "source_id UUID,",
        "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
        "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
    ]:
        assert column in sql
    # Text with a check, like other enums here, so new modes need no enum type change.
    assert "CHECK (retrieval_mode IN ('lexical', 'semantic', 'hybrid', 'reranked'))" in sql
    assert "FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE RESTRICT" in sql
    assert {index.name for index in ResearchSession.__table__.indexes} == {
        "ix_research_sessions_source_id"
    }
    assert Base.metadata.tables["research_sessions"] is ResearchSession.__table__


def test_hybrid_is_the_default_mode() -> None:
    column = ResearchSession.__table__.c.retrieval_mode
    assert column.default.arg is ResearchMode.HYBRID  # type: ignore[union-attr]
