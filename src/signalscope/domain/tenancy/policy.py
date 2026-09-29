import uuid
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import (
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    UnauthenticatedError,
)
from signalscope.domain.documents.model import Document
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.organizations.model import Organization
from signalscope.domain.sources.model import Source
from signalscope.domain.tenancy.scope import ContentScope
from signalscope.domain.users.model import User

ORGANIZATION_REQUIRED = "organization_id is required."
ORGANIZATION_NEEDS_AUTH = "organization_id can only be set when authentication is enabled."
ORGANIZATION_NOT_FOUND = "Organization was not found."
NOT_ALLOWED = "Your role in this organization does not allow this."


class ContentCapability(StrEnum):
    # Search and read documents, extracted data, timelines, dashboards and research.
    READ = "read"
    # Import files and add documents, and create research sessions and turns.
    CONTRIBUTE = "contribute"
    # Create, change and delete sources, their schedules and ingestion runs.
    MANAGE = "manage"


ROLE_CAPABILITIES = {
    OrganizationRole.VIEWER: frozenset({ContentCapability.READ}),
    OrganizationRole.MEMBER: frozenset({ContentCapability.READ, ContentCapability.CONTRIBUTE}),
    OrganizationRole.ADMIN: frozenset(ContentCapability),
    OrganizationRole.OWNER: frozenset(ContentCapability),
}


class ContentAccessPolicy:
    """The one place that decides which content a user may reach.

    The actor is None when authentication is disabled; then everything is
    allowed, as before organizations existed. Otherwise:

    - A broad query names one organization, and the actor must belong to it
      with a role that has the capability. System admins may name any
      organization.
    - Without an organization, only system admins may go on, and they see
      legacy content (sources without an organization), never every
      organization at once.
    - A single resource is checked against the organization stored on its
      source, never one given by the caller. Content the actor may not see
      is not found, so its existence is not revealed.
    """

    def __init__(self, session: AsyncSession, actor: User | None) -> None:
        self.session = session
        self.actor = actor

    async def scope(
        self,
        organization_id: uuid.UUID | None,
        capability: ContentCapability = ContentCapability.READ,
    ) -> ContentScope:
        """The scope for a broad query, such as a search or a list."""
        actor = self._active_actor()
        if actor is None:
            return ContentScope.unrestricted()
        if organization_id is None:
            if actor.is_system_admin:
                return ContentScope.legacy()
            raise InvalidInputError(ORGANIZATION_REQUIRED)
        if await self.session.get(Organization, organization_id) is None:
            raise NotFoundError(ORGANIZATION_NOT_FOUND)
        await self._check_role(actor, organization_id, capability, ORGANIZATION_NOT_FOUND)
        return ContentScope.organization(organization_id)

    async def new_content_owner(
        self, organization_id: uuid.UUID | None, capability: ContentCapability
    ) -> uuid.UUID | None:
        """The organization that will own new content, after checking the actor.

        With authentication on, new content always belongs to an organization,
        also for system admins: no new legacy content is made through the API.
        With authentication off, new content is legacy content, as before.
        """
        actor = self._active_actor()
        if actor is None:
            if organization_id is not None:
                raise InvalidInputError(ORGANIZATION_NEEDS_AUTH)
            return None
        if organization_id is None:
            raise InvalidInputError(ORGANIZATION_REQUIRED)
        await self.scope(organization_id, capability)
        return organization_id

    async def require(
        self,
        organization_id: uuid.UUID | None,
        capability: ContentCapability,
        not_found: str,
    ) -> None:
        """Check access to content owned by organization_id, or legacy content for None.

        not_found is the message when the actor may not see the content at all.
        """
        actor = self._active_actor()
        if actor is None:
            return
        if organization_id is None:
            if not actor.is_system_admin:
                raise NotFoundError(not_found)
            return
        await self._check_role(actor, organization_id, capability, not_found)

    async def require_read(self, organization_id: uuid.UUID | None, not_found: str) -> None:
        await self.require(organization_id, ContentCapability.READ, not_found)

    async def require_contribute(self, organization_id: uuid.UUID | None, not_found: str) -> None:
        await self.require(organization_id, ContentCapability.CONTRIBUTE, not_found)

    async def require_manage(self, organization_id: uuid.UUID | None, not_found: str) -> None:
        await self.require(organization_id, ContentCapability.MANAGE, not_found)

    async def authorize_source(
        self, source_id: uuid.UUID, capability: ContentCapability = ContentCapability.READ
    ) -> Source:
        """The source, if the actor may use it with the capability."""
        not_found = "Source was not found."
        source = await self.session.get(Source, source_id)
        if source is None:
            raise NotFoundError(not_found)
        await self.require(source.organization_id, capability, not_found)
        return source

    async def check_source_filter(self, source_id: uuid.UUID | None) -> None:
        """A source_id filter must name a source the actor may read.

        With authentication off any ID is accepted, as before: an unknown one
        simply matches nothing.
        """
        if source_id is not None and self._active_actor() is not None:
            await self.authorize_source(source_id)

    async def authorize_document(
        self, document_id: uuid.UUID, capability: ContentCapability = ContentCapability.READ
    ) -> Document:
        """The document, if the actor may use it. Its organization comes from its source."""
        not_found = "Document was not found."
        document = await self.session.get(Document, document_id)
        if document is None:
            raise NotFoundError(not_found)
        await self.require(await self.document_organization(document), capability, not_found)
        return document

    async def document_organization(self, document: Document) -> uuid.UUID | None:
        source = await self.session.get(Source, document.source_id)
        return None if source is None else source.organization_id

    def _active_actor(self) -> User | None:
        if self.actor is not None and not self.actor.is_active:
            raise UnauthenticatedError()
        return self.actor

    async def _check_role(
        self,
        actor: User,
        organization_id: uuid.UUID,
        capability: ContentCapability,
        not_found: str,
    ) -> None:
        if actor.is_system_admin:
            return
        membership = await self.session.get(OrganizationMembership, (organization_id, actor.id))
        if membership is None:
            raise NotFoundError(not_found)
        if capability not in ROLE_CAPABILITIES[membership.role]:
            raise ForbiddenError(NOT_ALLOWED)
