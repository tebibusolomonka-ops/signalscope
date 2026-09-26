from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

ENTITY_NAME_MAX_LENGTH = 300
ENTITY_TYPE_MAX_LENGTH = 50


class Entity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person, organization, place or other named thing found in documents.

    Two mentions belong to the same entity when their normalized names and
    types match. That is a simple first rule: it does not merge spelling
    variants, and it cannot tell apart two people with the same name.
    """

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("normalized_name", "entity_type"),
        CheckConstraint("btrim(canonical_name) <> ''", name="canonical_name_not_blank"),
        CheckConstraint("btrim(normalized_name) <> ''", name="normalized_name_not_blank"),
        CheckConstraint("btrim(entity_type) <> ''", name="entity_type_not_blank"),
    )

    # The name as it is shown, such as "Angela Merkel".
    canonical_name: Mapped[str] = mapped_column(String(ENTITY_NAME_MAX_LENGTH))
    # See normalize_entity_name.
    normalized_name: Mapped[str] = mapped_column(String(ENTITY_NAME_MAX_LENGTH))
    # A short label from the extraction model, such as "person" or "ORG". The
    # set of types is not fixed yet.
    entity_type: Mapped[str] = mapped_column(String(ENTITY_TYPE_MAX_LENGTH))
