import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.domain.blobs.repository import BlobCleanupTaskRepository
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.asset_repository import DocumentAssetRepository
from signalscope.domain.documents.files import prepare_file, stored_blob
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.repository import DocumentRepository
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob
from signalscope.domain.sources.model import SourceType
from signalscope.domain.sources.repository import SourceRepository
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.parsing.plain_text import title_from_filename
from signalscope.storage.blob import BlobStore


@dataclass(frozen=True, slots=True)
class ImportedFile:
    document: Document
    asset: DocumentAsset
    job: DocumentProcessingJob


class FileImportService:
    """Imports a raw file and queues it for processing.

    The document, its asset and its processing job are committed together.
    When that fails, the stored bytes are deleted again. The file is not
    parsed here. A processing worker does that later.
    """

    def __init__(self, session: AsyncSession, blobs: BlobStore, clock: Clock = utc_now) -> None:
        self.session = session
        self.blobs = blobs
        self.clock = clock
        self.sources = SourceRepository(session)
        self.documents = DocumentRepository(session)
        self.assets = DocumentAssetRepository(session)
        self.jobs = DocumentProcessingJobRepository(session)

    async def import_file(
        self, source_id: uuid.UUID, *, filename: str | None, content_type: str, data: bytes
    ) -> ImportedFile:
        source = await self.sources.get(source_id)
        if source is None:
            raise NotFoundError("Source was not found.")
        if source.type is not SourceType.UPLOAD:
            raise ConflictError(
                f"Files can only be imported into upload sources, not {source.type} sources."
            )
        file = prepare_file(filename, content_type, data)

        async with stored_blob(self.blobs, file.data, self._record_cleanup) as key:
            try:
                # Content stays empty until the file is parsed. content_hash is
                # left empty too, because it describes the text, not the raw bytes.
                document = await self.documents.add(
                    Document(source_id=source.id, title=title_from_filename(file.filename))
                )
                asset = await self.assets.add(file.to_asset(document.id, key))
                job = await self.jobs.add(
                    DocumentProcessingJob(
                        document_id=document.id, asset_id=asset.id, available_at=self.clock()
                    )
                )
                await self.session.commit()
            except Exception:
                await self.session.rollback()
                raise
        return ImportedFile(document=document, asset=asset, job=job)

    async def _record_cleanup(self, storage_key: str, reason: str) -> None:
        """Remember a blob that is left over, so it can be deleted later.

        The failed import already rolled its session back, so this starts a
        new transaction. Only the blob key is stored, never a path.
        """
        try:
            await BlobCleanupTaskRepository(self.session).add(storage_key, self.clock(), reason)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
