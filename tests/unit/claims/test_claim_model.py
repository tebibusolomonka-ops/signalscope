import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.claims.text import normalize_claim_text, normalize_claim_type


def sql_of(table: object) -> str:
    return str(CreateTable(table).compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "normalized"),
    [
        ("Unemployment fell to 5%.", "unemployment fell to 5%."),
        ("  Unemployment   fell\nto 5%.  ", "unemployment fell to 5%."),
        # Numbers and punctuation change the claim, so they stay.
        ("Unemployment fell to 5.5%!", "unemployment fell to 5.5%!"),
        ("STRASSE closed", "strasse closed"),
    ],
)
def test_normalize_claim_text(text: str, normalized: str) -> None:
    assert normalize_claim_text(text) == normalized


def test_claims_with_other_numbers_stay_apart() -> None:
    assert normalize_claim_text("Prices rose 5%.") != normalize_claim_text("Prices rose 6%.")


def test_normalize_claim_type() -> None:
    assert normalize_claim_type("  Statistic ") == "statistic"
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_claim_type(" ")


def test_claims_table() -> None:
    sql = sql_of(Claim.__table__)

    assert "text VARCHAR(500) NOT NULL" in sql
    assert "UNIQUE (normalized_text, claim_type)" in sql
    assert "CHECK (btrim(claim_type) <> '')" in sql
    assert Base.metadata.tables["claims"] is Claim.__table__


def test_claim_evidence_table() -> None:
    sql = sql_of(ClaimEvidence.__table__)

    assert "UNIQUE (chunk_id, start_char, end_char, provider, model)" in sql
    assert "CHECK (end_char > start_char)" in sql
    assert "CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))" in sql
    assert "FOREIGN KEY(claim_id) REFERENCES claims (id) ON DELETE RESTRICT" in sql
    assert "FOREIGN KEY(chunk_id) REFERENCES document_chunks (id) ON DELETE CASCADE" in sql
    assert Base.metadata.tables["claim_evidence"] is ClaimEvidence.__table__


def test_claim_extraction_jobs_table() -> None:
    from signalscope.domain.claims.job import ClaimExtractionJob, ClaimExtractionJobStatus

    sql = sql_of(ClaimExtractionJob.__table__)

    assert "lease_token UUID," in sql
    assert "UNIQUE (chunk_id, provider, model)" in sql
    assert "CHECK (status IN ('pending', 'running', 'completed', 'failed'))" in sql
    assert "FOREIGN KEY(chunk_id) REFERENCES document_chunks (id) ON DELETE CASCADE" in sql
    status = ClaimExtractionJob.__table__.c.status
    assert status.default.arg is ClaimExtractionJobStatus.PENDING  # type: ignore[union-attr]
    indexes = {index.name for index in ClaimExtractionJob.__table__.indexes}
    assert indexes == {"ix_claim_extraction_jobs_status_available_at"}
    assert Base.metadata.tables["claim_extraction_jobs"] is ClaimExtractionJob.__table__
