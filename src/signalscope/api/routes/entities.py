import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import StringConstraints

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.core.errors import NotFoundError
from signalscope.domain.entities.model import (
    ENTITY_NAME_MAX_LENGTH,
    ENTITY_TYPE_MAX_LENGTH,
    Entity,
)
from signalscope.domain.entities.repository import EntityRepository
from signalscope.domain.entities.schemas import EntityDetailRead, EntityMentionRead, EntityRead

router = APIRouter(prefix="/entities", tags=["Entities"])

NameQuery = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=ENTITY_NAME_MAX_LENGTH),
    Query(description="Part of the name, in any case."),
]
TypeQuery = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=ENTITY_TYPE_MAX_LENGTH),
    Query(description="The exact entity type, such as person."),
]


@router.get("")
async def list_entities(
    session: DatabaseSession,
    page: Pagination,
    query: NameQuery = None,
    entity_type: TypeQuery = None,
) -> Page[EntityRead]:
    """List entities found in documents, by name. Entities are read only."""
    summaries, total = await EntityRepository(session).list_page(
        query, entity_type, page.limit, page.offset
    )
    return Page[EntityRead](
        items=[_entity_read(summary.entity, summary.mention_count) for summary in summaries],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{entity_id}")
async def get_entity(entity_id: uuid.UUID, session: DatabaseSession) -> EntityDetailRead:
    """One entity with its mentions, the first 100 in document order."""
    repository = EntityRepository(session)
    entity = await repository.get(entity_id)
    if entity is None:
        raise NotFoundError("Entity was not found.")
    mentions, total = await repository.mentions(entity_id)
    return EntityDetailRead(
        entity=_entity_read(entity, total),
        mention_count=total,
        mentions=[
            EntityMentionRead(
                id=item.mention.id,
                document_id=item.mention.document_id,
                chunk_id=item.mention.chunk_id,
                surface_text=item.mention.surface_text,
                entity_type=item.mention.entity_type,
                start_char=item.mention.start_char,
                end_char=item.mention.end_char,
                confidence=item.mention.confidence,
                provider=item.mention.provider,
                model=item.mention.model,
                chunk_metadata=item.chunk_metadata,
            )
            for item in mentions
        ],
    )


def _entity_read(entity: Entity, mention_count: int) -> EntityRead:
    return EntityRead(
        id=entity.id,
        canonical_name=entity.canonical_name,
        normalized_name=entity.normalized_name,
        entity_type=entity.entity_type,
        mention_count=mention_count,
        created_at=entity.created_at,
    )
