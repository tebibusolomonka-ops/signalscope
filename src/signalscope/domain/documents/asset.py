import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

STORAGE_KEY_MAX_LENGTH = 255
FILENAME_MAX_LENGTH = 255
CONTENT_TYPE_MAX_LENGTH = 255
SHA256_LENGTH = 64


class DocumentAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The raw file behind a document, such as an imported PDF.

    The bytes live in a blob store. This row only describes them.
    """

    __tablename__ = "document_assets"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="size_bytes_not_negative"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_is_hex"),
    )

    # Restrict, so a document is never deleted while its file may still be stored.
    # Unique, because a document has at most one raw file for now.
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), unique=True
    )
    # A key in the blob store, never a file system path.
    storage_key: Mapped[str] = mapped_column(String(STORAGE_KEY_MAX_LENGTH), unique=True)
    # Only the file name, without any folders the client sent.
    filename: Mapped[str | None] = mapped_column(String(FILENAME_MAX_LENGTH))
    content_type: Mapped[str] = mapped_column(String(CONTENT_TYPE_MAX_LENGTH))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # Hex SHA-256 of the raw bytes.
    sha256: Mapped[str] = mapped_column(String(SHA256_LENGTH))
