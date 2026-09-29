import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import StringConstraints

from signalscope.api.dependencies import DatabaseSession, DatabaseSessionFactory
from signalscope.api.pagination import Page, Pagination
from signalscope.api.tenancy import OrganizationFilter, Policy, ReadScope
from signalscope.core.errors import NotFoundError
from signalscope.domain.entities.coverage import EntityCoverageService
from signalscope.domain.entities.model import (
    ENTITY_NAME_MAX_LENGTH,
    ENTITY_TYPE_MAX_LENGTH,
    Entity,
)
from signalscope.domain.entities.repository import EntityRepository
from signalscope.domain.entities.schemas import (
    EntityCoverageRead,
    EntityDetailRead,
    EntityMentionRead,
    EntityRead,
)
from signalscope.entities.models import GLINER_MULTI

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
    scope: ReadScope,
    query: NameQuery = None,
    entity_type: TypeQuery = None,
) -> Page[EntityRead]:
    """List entities found in documents, by name. Entities are read only.

    With authentication on, only entities mentioned in the organization_id
    organization's documents are listed, with those mentions counted.
    """
    summaries, total = await EntityRepository(session).list_page(
        query, entity_type, page.limit, page.offset, scope
    )
    return Page[EntityRead](
        items=[_entity_read(summary.entity, summary.mention_count) for summary in summaries],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


# Declared before /{entity_id}, so "coverage" is not read as an entity ID.
@router.get("/coverage")
async def entity_coverage(
    session_factory: DatabaseSessionFactory,
    policy: Policy,
    organization_id: OrganizationFilter = None,
    document_id: uuid.UUID | None = None,
) -> EntityCoverageRead:
    """Count the chunks the local GLiNER model has read.

    The numbers come from the database, so the model does not need to be
    installed or loaded. document_id limits them to one document. With
    authentication on, the counts cover the organization_id organization, or
    the document's organization when document_id is given.
    """
    spec = GLINER_MULTI
    service = EntityCoverageService(session_factory)
    if document_id is None:
        scope = await policy.scope(organization_id)
        coverage = await service.overall(spec.provider, spec.model, scope)
    else:
        await policy.authorize_document(document_id)
        coverage = await service.for_document(document_id, spec.provider, spec.model)
    return EntityCoverageRead(
        provider=spec.provider,
        model=spec.model,
        document_id=document_id,
        chunk_count=coverage.chunk_count,
        extracted_count=coverage.extracted_count,
        pending_count=coverage.pending_count,
        failed_count=coverage.failed_count,
        coverage=(
            coverage.extracted_count / coverage.chunk_count if coverage.chunk_count else None
        ),
    )


@router.get("/{entity_id}")
async def get_entity(
    entity_id: uuid.UUID, session: DatabaseSession, scope: ReadScope
) -> EntityDetailRead:
    """One entity with its mentions, the first 100 in document order.

    With authentication on, only mentions in the organization_id
    organization's documents; an entity without any there is not found.
    """
    repository = EntityRepository(session)
    entity = await repository.get(entity_id)
    if entity is None:
        raise NotFoundError("Entity was not found.")
    mentions, total = await repository.mentions(entity_id, scope=scope)
    if total == 0 and not scope.is_unrestricted:
        raise NotFoundError("Entity was not found.")
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
