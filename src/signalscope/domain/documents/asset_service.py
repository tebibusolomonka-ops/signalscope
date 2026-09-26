import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.db.errors import is_unique_violation
from signalscope.domain.blobs.repository import BlobCleanupTaskRepository
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.asset_repository import DocumentAssetRepository
from signalscope.domain.documents.files import prepare_file, stored_blob
from signalscope.domain.documents.repository import DocumentRepository
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.storage.blob import BlobStore


class DocumentAssetService:
    """Stores the raw file of a document.

    The bytes go to the blob store and the metadata to the database. When the
    database work fails, the new blob is deleted again.
    """

    def __init__(self, session: AsyncSession, blobs: BlobStore, clock: Clock = utc_now) -> None:
        self.session = session
        self.blobs = blobs
        self.clock = clock
        self.documents = DocumentRepository(session)
        self.assets = DocumentAssetRepository(session)

    async def attach(
        self, document_id: uuid.UUID, *, filename: str | None, content_type: str, data: bytes
    ) -> DocumentAsset:
        file = prepare_file(filename, content_type, data)
        if await self.documents.get(document_id) is None:
            raise NotFoundError("Document was not found.")
        if await self.assets.get_by_document(document_id) is not None:
            raise ConflictError("Document already has a stored file.")

        async with stored_blob(self.blobs, file.data, self._record_cleanup) as key:
            try:
                asset = await self.assets.add(file.to_asset(document_id, key))
                await self.session.commit()
            except IntegrityError as error:
                await self.session.rollback()
                # Another request stored a file for the document at the same time.
                if is_unique_violation(error):
                    raise ConflictError("Document already has a stored file.") from error
                raise
            except Exception:
                await self.session.rollback()
                raise
        return asset

    async def get(self, document_id: uuid.UUID) -> DocumentAsset:
        asset = await self.assets.get_by_document(document_id)
        if asset is None:
            raise NotFoundError("Document has no stored file.")
        return asset

    async def read(self, asset: DocumentAsset) -> bytes:
        return await self.blobs.get(asset.storage_key)

    async def _record_cleanup(self, storage_key: str, reason: str) -> None:
        """Remember a blob that is left over, so it can be deleted later."""
        try:
            await BlobCleanupTaskRepository(self.session).add(storage_key, self.clock(), reason)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
