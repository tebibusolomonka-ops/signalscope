import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from signalscope.api.dependencies import DatabaseSession
from signalscope.domain.documents.schemas import DocumentCreate, DocumentRead
from signalscope.domain.documents.service import DocumentService

router = APIRouter(prefix="/documents", tags=["Documents"])


def get_document_service(session: DatabaseSession) -> DocumentService:
    return DocumentService(session)


Documents = Annotated[DocumentService, Depends(get_document_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_document(data: DocumentCreate, documents: Documents) -> DocumentRead:
    return DocumentRead.model_validate(await documents.create(data))


@router.get("")
async def list_documents(documents: Documents) -> list[DocumentRead]:
    return [DocumentRead.model_validate(document) for document in await documents.list_all()]


@router.get("/{document_id}")
async def get_document(document_id: uuid.UUID, documents: Documents) -> DocumentRead:
    return DocumentRead.model_validate(await documents.get(document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, documents: Documents) -> None:
    await documents.delete(document_id)
