import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.search.embedding_model import ChunkEmbedding


class ChunkEmbeddingRepository:
    """Database access for chunk embeddings. It never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, chunk_id: uuid.UUID, provider: str, model: str) -> ChunkEmbedding | None:
        result = await self.session.scalars(
            select(ChunkEmbedding).where(
                ChunkEmbedding.chunk_id == chunk_id,
                ChunkEmbedding.provider == provider,
                ChunkEmbedding.model == model,
            )
        )
        return result.one_or_none()

    async def save(
        self,
        chunk_id: uuid.UUID,
        provider: str,
        model: str,
        chunk_text_hash: str,
        vector: Sequence[float],
    ) -> None:
        """Store the vector of a chunk, replacing an earlier one from the same model."""
        values = {
            "dimensions": len(vector),
            "chunk_text_hash": chunk_text_hash,
            "embedding": list(vector),
        }
        statement = insert(ChunkEmbedding).values(
            id=uuid.uuid4(), chunk_id=chunk_id, provider=provider, model=model, **values
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["chunk_id", "provider", "model"],
                set_={**values, "updated_at": func.now()},
            )
        )
