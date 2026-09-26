import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from pydantic import AwareDatetime

from signalscope.api.dependencies import Blobs, DatabaseSession
from signalscope.api.pagination import Page, Pagination
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

router = APIRouter(prefix="/documents", tags=["Documents"])


def get_document_service(session: DatabaseSession, blobs: Blobs) -> DocumentService:
    return DocumentService(session, blobs)


def get_revision_service(session: DatabaseSession) -> DocumentRevisionService:
    return DocumentRevisionService(session)


def get_document_filters(
    source_id: uuid.UUID | None = None,
    language: Language | None = None,
    published_from: AwareDatetime | None = None,
    published_to: AwareDatetime | None = None,
) -> DocumentFilters:
    return DocumentFilters(
        source_id=source_id,
        language=language,
        published_from=published_from,
        published_to=published_to,
    )


Documents = Annotated[DocumentService, Depends(get_document_service)]
Filters = Annotated[DocumentFilters, Depends(get_document_filters)]
Revisions = Annotated[DocumentRevisionService, Depends(get_revision_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_document(data: DocumentCreate, documents: Documents) -> DocumentRead:
    return DocumentRead.model_validate(await documents.create(data))


@router.get("")
async def list_documents(
    filters: Filters, page: Pagination, documents: Documents
) -> Page[DocumentRead]:
    items, total = await documents.list_page(filters, page.limit, page.offset)
    return Page[DocumentRead](
        items=[DocumentRead.model_validate(document) for document in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{document_id}")
async def get_document(document_id: uuid.UUID, documents: Documents) -> DocumentRead:
    return DocumentRead.model_validate(await documents.get(document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, documents: Documents) -> None:
    await documents.delete(document_id)


@router.get("/{document_id}/revisions")
async def list_document_revisions(
    document_id: uuid.UUID, revisions: Revisions
) -> DocumentRevisionList:
    """Earlier states of a document, oldest first. The text is left out."""
    items = await revisions.list(document_id)
    return DocumentRevisionList(
        items=[DocumentRevisionSummary.from_revision(item) for item in items]
    )


@router.get("/{document_id}/revisions/{version}")
async def get_document_revision(
    document_id: uuid.UUID, version: Annotated[int, Path(ge=1)], revisions: Revisions
) -> DocumentRevisionRead:
    """One earlier state of a document, with its full text."""
    return DocumentRevisionRead.model_validate(await revisions.get(document_id, version))
