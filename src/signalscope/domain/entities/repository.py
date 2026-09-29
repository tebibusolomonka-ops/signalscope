import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.entities.names import normalize_entity_name, normalize_entity_type
from signalscope.domain.tenancy.scope import ContentScope

# The most mentions an entity detail shows. mention_count still counts them all.
MAX_DETAIL_MENTIONS = 100
UNRESTRICTED = ContentScope.unrestricted()


@dataclass(frozen=True, slots=True)
class EntitySummary:
    entity: Entity
    mention_count: int


@dataclass(frozen=True, slots=True)
class MentionWithChunk:
    mention: EntityMention
    # Where the chunk came from, such as {"page_number": 3}.
    chunk_metadata: dict[str, Any]


class EntityRepository:
    """Read access to entities and their mentions. It never commits.

    Entities are shared names, not owned by an organization. In a scope, an
    entity is only seen through its mentions in that scope: it is listed when
    it has at least one, and its counts and mentions come from those only.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_page(
        self,
        query: str | None,
        entity_type: str | None,
        limit: int,
        offset: int,
        scope: ContentScope = UNRESTRICTED,
    ) -> tuple[list[EntitySummary], int]:
        """Entities whose normalized name contains the normalized query, by name.

        This is plain substring matching, not fuzzy search. Unrestricted, every
        entity is listed, also without mentions, as before organizations.
        """
        conditions = _conditions(query, entity_type)
        visible = scope.document_condition(EntityMention.document_id)
        mention_counts = (
            select(EntityMention.entity_id, func.count().label("mentions"))
            .where(visible)
            .group_by(EntityMention.entity_id)
            .subquery()
        )
        if scope.is_unrestricted:
            statement = select(Entity, func.coalesce(mention_counts.c.mentions, 0)).outerjoin(
                mention_counts, mention_counts.c.entity_id == Entity.id
            )
        else:
            # One row per entity, since the counts are grouped by entity first.
            statement = select(Entity, mention_counts.c.mentions).join(
                mention_counts, mention_counts.c.entity_id == Entity.id
            )
            conditions.append(Entity.id.in_(select(EntityMention.entity_id).where(visible)))
        rows = await self.session.execute(
            statement.where(*conditions)
            .order_by(Entity.normalized_name, Entity.entity_type, Entity.id)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(Entity).where(*conditions)
        )
        return [EntitySummary(entity, count) for entity, count in rows], total or 0

    async def get(self, entity_id: uuid.UUID) -> Entity | None:
        return await self.session.get(Entity, entity_id)

    async def mentions(
        self,
        entity_id: uuid.UUID,
        limit: int = MAX_DETAIL_MENTIONS,
        scope: ContentScope = UNRESTRICTED,
    ) -> tuple[list[MentionWithChunk], int]:
        """The mentions of an entity in scope, in document order, and how many there are."""
        visible = scope.document_condition(EntityMention.document_id)
        rows = await self.session.execute(
            select(EntityMention, DocumentChunk.chunk_metadata)
            .join(DocumentChunk, DocumentChunk.id == EntityMention.chunk_id)
            .where(EntityMention.entity_id == entity_id, visible)
            .order_by(EntityMention.document_id, DocumentChunk.position, EntityMention.start_char)
            .limit(limit)
        )
        total = await self.session.scalar(
            select(func.count())
            .select_from(EntityMention)
            .where(EntityMention.entity_id == entity_id, visible)
        )
        return [MentionWithChunk(mention, dict(metadata)) for mention, metadata in rows], total or 0


def _conditions(query: str | None, entity_type: str | None) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if query is not None:
        # The query is taken as plain text, so % and _ have no special meaning.
        conditions.append(
            Entity.normalized_name.contains(normalize_entity_name(query), autoescape=True)
        )
    if entity_type is not None:
        conditions.append(Entity.entity_type == normalize_entity_type(entity_type))
    return conditions
