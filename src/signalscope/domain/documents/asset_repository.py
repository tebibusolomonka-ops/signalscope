import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.asset import DocumentAsset


class DocumentAssetRepository:
    """Database access for document assets.

    It never commits. The caller decides when the transaction ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, asset: DocumentAsset) -> DocumentAsset:
        self.session.add(asset)
        # Flush so the database fills in the timestamps and reports errors now.
        await self.session.flush()
        return asset

    async def get(self, asset_id: uuid.UUID) -> DocumentAsset | None:
        return await self.session.get(DocumentAsset, asset_id)

    async def get_by_document(self, document_id: uuid.UUID) -> DocumentAsset | None:
        result = await self.session.scalars(
            select(DocumentAsset).where(DocumentAsset.document_id == document_id)
        )
        return result.one_or_none()
