import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.domain.documents.chunk import EMPTY_JSON_OBJECT
from signalscope.domain.search.embedding_model import MODEL_MAX_LENGTH, PROVIDER_MAX_LENGTH

# Short enough for the unique index, even for text in scripts that take
# several bytes per character.
CLAIM_TEXT_MAX_LENGTH = 500
CLAIM_TYPE_MAX_LENGTH = 50
SURFACE_TEXT_MAX_LENGTH = 2000


class Claim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A statement that documents make, such as "Unemployment fell to 5%".

    Claims are the same when their normalized text and type are the same. This
    is exact matching only: two claims that say the same thing in other words
    stay separate. Nothing here says whether a claim is true.
    """

    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("normalized_text", "claim_type"),
        CheckConstraint("btrim(text) <> ''", name="text_not_blank"),
        CheckConstraint("btrim(normalized_text) <> ''", name="normalized_text_not_blank"),
        CheckConstraint("btrim(claim_type) <> ''", name="claim_type_not_blank"),
    )

    # The claim as it is shown.
    text: Mapped[str] = mapped_column(String(CLAIM_TEXT_MAX_LENGTH))
    # See normalize_claim_text.
    normalized_text: Mapped[str] = mapped_column(String(CLAIM_TEXT_MAX_LENGTH))
    # A short label from the extraction model, such as "statistic". Not fixed yet.
    claim_type: Mapped[str] = mapped_column(String(CLAIM_TYPE_MAX_LENGTH))


class ClaimEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One place in a chunk that makes a claim, as found by one model.

    start_char and end_char point into DocumentChunk.text. Evidence goes away
    with its chunk. A claim cannot be deleted while evidence points to it.
    """

    __tablename__ = "claim_evidence"
    __table_args__ = (
        UniqueConstraint("chunk_id", "start_char", "end_char", "provider", "model"),
        CheckConstraint("start_char >= 0", name="start_char_not_negative"),
        CheckConstraint("end_char > start_char", name="end_char_after_start_char"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_between_zero_and_one",
        ),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_is_object"),
    )

    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), index=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE")
    )
    # The words in the chunk that make the claim.
    surface_text: Mapped[str] = mapped_column(String(SURFACE_TEXT_MAX_LENGTH))
    start_char: Mapped[int]
    end_char: Mapped[int]
    # How sure the model was, from 0 to 1, when it says.
    confidence: Mapped[float | None]
    provider: Mapped[str] = mapped_column(String(PROVIDER_MAX_LENGTH))
    model: Mapped[str] = mapped_column(String(MODEL_MAX_LENGTH))
    # Anything else the model reports. "metadata" is taken on SQLAlchemy models.
    evidence_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=EMPTY_JSON_OBJECT
    )
