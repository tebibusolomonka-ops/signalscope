import uuid

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.organizations.membership import OrganizationRole
from signalscope.domain.tenancy.policy import ROLE_CAPABILITIES, ContentCapability
from signalscope.domain.tenancy.scope import ContentScope, ScopeKind

HARBOUR = uuid.uuid4()
RIVER = uuid.uuid4()


def sql(scope: ContentScope) -> str:
    statement = select(DocumentChunk.id).where(scope.chunk_condition(DocumentChunk.id))
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def test_allows() -> None:
    organization = ContentScope.organization(HARBOUR)

    assert ContentScope.unrestricted().allows(None) and ContentScope.unrestricted().allows(RIVER)
    assert organization.allows(HARBOUR)
    assert not organization.allows(RIVER) and not organization.allows(None)
    assert ContentScope.legacy().allows(None)
    assert not ContentScope.legacy().allows(HARBOUR)


def test_conditions_follow_the_source() -> None:
    organization = sql(ContentScope.organization(HARBOUR))
    legacy = sql(ContentScope.legacy())

    assert "document_chunks.id IN (SELECT document_chunks.id" in organization
    assert "documents.source_id IN (SELECT sources.id" in organization
    assert f"sources.organization_id = '{HARBOUR}'" in organization
    assert "sources.organization_id IS NULL" in legacy
    assert "sources" not in sql(ContentScope.unrestricted())
    assert ContentScope.unrestricted().kind is ScopeKind.UNRESTRICTED


def test_role_capabilities() -> None:
    read, contribute, manage = (
        ContentCapability.READ,
        ContentCapability.CONTRIBUTE,
        ContentCapability.MANAGE,
    )

    expected = {
        OrganizationRole.VIEWER: {read},
        OrganizationRole.MEMBER: {read, contribute},
        OrganizationRole.ADMIN: {read, contribute, manage},
        OrganizationRole.OWNER: {read, contribute, manage},
    }
    found = dict(ROLE_CAPABILITIES)
    assert found == expected
