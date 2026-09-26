import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError, ServiceUnavailableError
from signalscope.db.errors import is_foreign_key_violation, is_unique_violation
from signalscope.domain.documents.asset_repository import DocumentAssetRepository
from signalscope.domain.documents.extraction_repository import DocumentExtractionRepository
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.repository import DocumentFilters, DocumentRepository
from signalscope.domain.documents.schemas import DocumentCreate
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import ProcessingJobStatus
from signalscope.domain.sources.repository import SourceRepository
from signalscope.storage.blob import BlobStorageError, BlobStore

logger = logging.getLogger(__name__)


class DocumentService:
    """Document operations used by the API.

    Writes commit before they return. When a write fails, the session is
    rolled back and the error is raised again.
    """

    def __init__(self, session: AsyncSession, blobs: BlobStore | None = None) -> None:
        self.session = session
        # Only needed to delete documents that have a stored file.
        self.blobs = blobs
        self.documents = DocumentRepository(session)
        self.sources = SourceRepository(session)
        self.assets = DocumentAssetRepository(session)
        self.extractions = DocumentExtractionRepository(session)
        self.jobs = DocumentProcessingJobRepository(session)

    async def create(self, data: DocumentCreate) -> Document:
        if await self.sources.get(data.source_id) is None:
            raise NotFoundError("Source was not found.")
        document = Document(**data.model_dump())
        try:
            await self.documents.add(document)
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            if is_unique_violation(error):
                raise ConflictError("Document already exists for this source.") from error
            raise
        except Exception:
            await self.session.rollback()
            raise
        return document

    async def get(self, document_id: uuid.UUID) -> Document:
        document = await self.documents.get(document_id)
        if document is None:
            raise NotFoundError("Document was not found.")
        return document

    async def list_page(
        self, filters: DocumentFilters, limit: int, offset: int
    ) -> tuple[list[Document], int]:
        """Return one page of matching documents and the total number that match."""
        items = await self.documents.list_page(filters, limit, offset)
        return items, await self.documents.count(filters)

    async def delete(self, document_id: uuid.UUID) -> None:
        """Delete a document with its stored file and everything made from it.

        The database rows go first, in one transaction. The file is deleted
        only after that commit, so a failed delete never leaves rows that
        point to a missing file. If the file cannot be deleted, it is left
        behind and logged.
        """
        try:
            asset = await self.assets.get_by_document(document_id)
            if asset is not None and self.blobs is None:
                raise ServiceUnavailableError("File storage is not configured.")
            jobs = await self.jobs.lock_for_document(document_id)
            if any(job.status is ProcessingJobStatus.RUNNING for job in jobs):
                raise ConflictError("Document is being processed. Try again later.")
            await self.jobs.delete_for_document(document_id)
            await self.extractions.delete_for_document(document_id)
            if asset is not None:
                await self.assets.delete(asset.id)
            # Chunks are deleted with the document by the database.
            deleted = await self.documents.delete(document_id)
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            if is_foreign_key_violation(error):
                raise ConflictError("Document is still in use and cannot be deleted.") from error
            raise
        except Exception:
            await self.session.rollback()
            raise
        if not deleted:
            raise NotFoundError("Document was not found.")
        if asset is not None and self.blobs is not None:
            await self._delete_blob(self.blobs, asset.storage_key)

    async def _delete_blob(self, blobs: BlobStore, key: str) -> None:
        try:
            await blobs.delete(key)
        except BlobStorageError:
            logger.exception("Could not delete blob %s of a deleted document", key)
