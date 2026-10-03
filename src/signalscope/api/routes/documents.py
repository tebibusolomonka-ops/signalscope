import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, status
from pydantic import AwareDatetime

from signalscope.api.dependencies import Blobs, DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.api.tenancy import OrganizationFilter, Policy, ReadScope
from signalscope.core.errors import InvalidInputError, ServiceUnavailableError
from signalscope.domain.documents.asset import FILENAME_MAX_LENGTH
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.files import MAX_FILE_BYTES
from signalscope.domain.documents.repository import DocumentFilters
from signalscope.domain.documents.revision_service import DocumentRevisionService
from signalscope.domain.documents.schemas import (
    DocumentChunkRead,
    DocumentCreate,
    DocumentFileRead,
    DocumentRead,
    DocumentRevisionList,
    DocumentRevisionRead,
    DocumentRevisionSummary,
    FileUploadLimits,
    Language,
)
from signalscope.domain.documents.service import DocumentService
from signalscope.domain.processing.file_import import FileImportService
from signalscope.domain.tenancy.policy import ContentCapability
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.parsing.types import UnsupportedDocumentTypeError

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


@router.get("/files/limits")
async def file_upload_limits() -> FileUploadLimits:
    """The content types and size that file uploads accept."""
    return FileUploadLimits(
        content_types=create_default_parser_registry().content_types(), max_bytes=MAX_FILE_BYTES
    )


@router.post("/files", status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    source_id: uuid.UUID,
    session: DatabaseSession,
    blobs: Blobs,
    policy: Policy,
    organization_id: OrganizationFilter = None,
    filename: Annotated[str | None, Query(max_length=FILENAME_MAX_LENGTH)] = None,
) -> DocumentFileRead:
    """Store the request body as a new document of an upload source and queue it.

    The body is the raw file and Content-Type is its media type. A processing
    worker parses it later, like import-file. Needs the member role or higher
    in the source's organization; with organization_id, the source must
    belong to that organization.
    """
    await policy.authorize_source(source_id, ContentCapability.CONTRIBUTE)
    if blobs is None:
        raise ServiceUnavailableError("File storage is not configured.")
    content_type = request.headers.get("content-type", "")
    try:
        create_default_parser_registry().get(content_type)
    except UnsupportedDocumentTypeError as error:
        raise InvalidInputError(str(error)) from error
    imported = await FileImportService(session, blobs).import_file(
        source_id,
        filename=filename,
        content_type=content_type,
        data=await _read_body(request),
        organization_id=organization_id,
    )
    return DocumentFileRead(
        document=DocumentRead.model_validate(imported.document),
        filename=imported.asset.filename,
        content_type=imported.asset.content_type,
        size_bytes=imported.asset.size_bytes,
        processing_job_id=imported.job.id,
    )


async def _read_body(request: Request) -> bytes:
    """The request body, refused as soon as it is larger than a file may be."""
    too_large = InvalidInputError(f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_FILE_BYTES:
        raise too_large
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_FILE_BYTES:
            raise too_large
    if not data:
        raise InvalidInputError("The file is empty.")
    return bytes(data)


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


@router.get("/{document_id}/chunks")
async def list_document_chunks(
    document_id: uuid.UUID, session: DatabaseSession, policy: Policy, page: Pagination
) -> Page[DocumentChunkRead]:
    """A document's chunks in position order, for reading or focusing one piece.

    The document's organization comes from its source; a document the caller
    may not see is not found. With authentication off it works as before.
    """
    await policy.authorize_document(document_id)
    chunks = DocumentChunkRepository(session)
    items = await chunks.list_page(document_id, page.limit, page.offset)
    total = await chunks.count_for_document(document_id)
    return Page[DocumentChunkRead](
        items=[DocumentChunkRead.from_chunk(chunk) for chunk in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


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
