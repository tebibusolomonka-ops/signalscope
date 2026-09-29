import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from pydantic import AwareDatetime

from signalscope.api.dependencies import Blobs, DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.api.tenancy import Policy, ReadScope
from signalscope.domain.documents.repository import DocumentFilters
from signalscope.domain.documents.revision_service import DocumentRevisionService
from signalscope.domain.documents.schemas import (
    DocumentCreate,
    DocumentRead,
    DocumentRevisionList,
    DocumentRevisionRead,
    DocumentRevisionSummary,
    Language,
)
from signalscope.domain.documents.service import DocumentService
from signalscope.domain.tenancy.policy import ContentCapability

router = APIRouter(prefix="/documents", tags=["Documents"])


def get_document_service(session: DatabaseSession, blobs: Blobs) -> DocumentService:
    return DocumentService(session, blobs)


def get_revision_service(session: DatabaseSession) -> DocumentRevisionService:
    return DocumentRevisionService(session)


async def get_document_filters(
    policy: Policy,
    scope: ReadScope,
    source_id: uuid.UUID | None = None,
    language: Language | None = None,
    published_from: AwareDatetime | None = None,
    published_to: AwareDatetime | None = None,
) -> DocumentFilters:
    await policy.check_source_filter(source_id)
    return DocumentFilters(
        source_id=source_id,
        language=language,
        published_from=published_from,
        published_to=published_to,
        scope=scope,
    )


Documents = Annotated[DocumentService, Depends(get_document_service)]
Filters = Annotated[DocumentFilters, Depends(get_document_filters)]
Revisions = Annotated[DocumentRevisionService, Depends(get_revision_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_document(
    data: DocumentCreate, documents: Documents, policy: Policy
) -> DocumentRead:
    """Add a document to a source. Needs the member role or higher in its organization."""
    await policy.authorize_source(data.source_id, ContentCapability.CONTRIBUTE)
    return DocumentRead.model_validate(await documents.create(data))


@router.get("")
async def list_documents(
    filters: Filters, page: Pagination, documents: Documents
) -> Page[DocumentRead]:
    """Documents of the organization_id organization, or legacy ones for system admins."""
    items, total = await documents.list_page(filters, page.limit, page.offset)
    return Page[DocumentRead](
        items=[DocumentRead.model_validate(document) for document in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{document_id}")
async def get_document(document_id: uuid.UUID, policy: Policy) -> DocumentRead:
    return DocumentRead.model_validate(await policy.authorize_document(document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, documents: Documents, policy: Policy) -> None:
    """Delete a document and what was made from it. Needs the member role or higher."""
    await policy.authorize_document(document_id, ContentCapability.CONTRIBUTE)
    await documents.delete(document_id)


@router.get("/{document_id}/revisions")
async def list_document_revisions(
    document_id: uuid.UUID, revisions: Revisions, policy: Policy
) -> DocumentRevisionList:
    """Earlier states of a document, oldest first. The text is left out."""
    await policy.authorize_document(document_id)
    items = await revisions.list(document_id)
    return DocumentRevisionList(
        items=[DocumentRevisionSummary.from_revision(item) for item in items]
    )


@router.get("/{document_id}/revisions/{version}")
async def get_document_revision(
    document_id: uuid.UUID,
    version: Annotated[int, Path(ge=1)],
    revisions: Revisions,
    policy: Policy,
) -> DocumentRevisionRead:
    """One earlier state of a document, with its full text."""
    await policy.authorize_document(document_id)
    return DocumentRevisionRead.model_validate(await revisions.get(document_id, version))
