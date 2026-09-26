import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import AwareDatetime

from signalscope.api.dependencies import Blobs, DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.domain.documents.repository import DocumentFilters
from signalscope.domain.documents.schemas import DocumentCreate, DocumentRead, Language
from signalscope.domain.documents.service import DocumentService

router = APIRouter(prefix="/documents", tags=["Documents"])


def get_document_service(session: DatabaseSession, blobs: Blobs) -> DocumentService:
    return DocumentService(session, blobs)


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
