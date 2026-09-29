import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, select, true

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source


class ScopeKind(StrEnum):
    # Authentication is off: all content, as before organizations existed.
    UNRESTRICTED = "unrestricted"
    # Content of one organization.
    ORGANIZATION = "organization"
    # Content of legacy sources, which have no organization. System admins only.
    LEGACY = "legacy"


@dataclass(frozen=True, slots=True)
class ContentScope:
    """Which content a request may see.

    Content belongs to an organization through its source. The conditions
    below are SQL, meant for the WHERE clause, so rows outside the scope are
    removed before any ranking, limit or count.
    """

    kind: ScopeKind
    organization_id: uuid.UUID | None = None

    @classmethod
    def unrestricted(cls) -> "ContentScope":
        return cls(ScopeKind.UNRESTRICTED)

    @classmethod
    def organization(cls, organization_id: uuid.UUID) -> "ContentScope":
        return cls(ScopeKind.ORGANIZATION, organization_id)

    @classmethod
    def legacy(cls) -> "ContentScope":
        return cls(ScopeKind.LEGACY)

    @property
    def is_unrestricted(self) -> bool:
        return self.kind is ScopeKind.UNRESTRICTED

    def allows(self, organization_id: uuid.UUID | None) -> bool:
        """Whether content owned by organization_id (None for legacy) is in scope."""
        if self.kind is ScopeKind.UNRESTRICTED:
            return True
        if self.kind is ScopeKind.LEGACY:
            return organization_id is None
        return organization_id == self.organization_id

    def owner_condition(self, column: Any) -> ColumnElement[bool]:
        """Rows whose organization column is in scope."""
        if self.kind is ScopeKind.UNRESTRICTED:
            return true()
        if self.kind is ScopeKind.LEGACY:
            return column.is_(None)  # type: ignore[no-any-return]
        return column == self.organization_id  # type: ignore[no-any-return]

    def source_condition(self, source_id: Any) -> ColumnElement[bool]:
        """Rows whose source ID column points at a source in scope."""
        if self.kind is ScopeKind.UNRESTRICTED:
            return true()
        visible = select(Source.id).where(self.owner_condition(Source.organization_id))
        return source_id.in_(visible)  # type: ignore[no-any-return]

    def document_condition(self, document_id: Any) -> ColumnElement[bool]:
        """Rows whose document ID column points at a document in scope."""
        if self.kind is ScopeKind.UNRESTRICTED:
            return true()
        visible = select(Document.id).where(self.source_condition(Document.source_id))
        return document_id.in_(visible)  # type: ignore[no-any-return]

    def chunk_condition(self, chunk_id: Any) -> ColumnElement[bool]:
        """Rows whose chunk ID column points at a chunk in scope."""
        if self.kind is ScopeKind.UNRESTRICTED:
            return true()
        visible = select(DocumentChunk.id).where(self.document_condition(DocumentChunk.document_id))
        return chunk_id.in_(visible)  # type: ignore[no-any-return]
