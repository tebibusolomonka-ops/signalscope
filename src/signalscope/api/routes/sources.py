import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.api.tenancy import Policy, ReadScope
from signalscope.domain.sources.comparison import SourceComparisonService
from signalscope.domain.sources.provenance import SourceProvenanceService
from signalscope.domain.sources.scheduling import SourceScheduleService
from signalscope.domain.sources.schemas import (
    ComparedSourceRead,
    SourceComparisonRead,
    SourceComparisonRequest,
    SourceCreate,
    SourceProvenanceRead,
    SourceRead,
    SourceScheduleUpdate,
)
from signalscope.domain.sources.service import SourceService
from signalscope.domain.tenancy.policy import ContentCapability

router = APIRouter(prefix="/sources", tags=["Sources"])


def get_source_service(session: DatabaseSession) -> SourceService:
    return SourceService(session)


Sources = Annotated[SourceService, Depends(get_source_service)]


def get_source_schedule_service(session: DatabaseSession) -> SourceScheduleService:
    return SourceScheduleService(session)


Schedules = Annotated[SourceScheduleService, Depends(get_source_schedule_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_source(data: SourceCreate, sources: Sources, policy: Policy) -> SourceRead:
    """Add a source. With authentication on, it needs the organization_id of an
    organization where you are an owner or admin, and the source belongs to it."""
    await policy.new_content_owner(data.organization_id, ContentCapability.MANAGE)
    return SourceRead.model_validate(await sources.create(data))


@router.get("")
async def list_sources(
    page: Pagination,
    sources: Sources,
    scope: ReadScope,
    query: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description="Keep sources whose name or URL contains this.",
        ),
    ] = None,
) -> Page[SourceRead]:
    """Sources of the organization_id organization, or legacy sources for system admins.

    query keeps sources whose name or URL contains it, so a picker can search.
    """
    items, total = await sources.list_page(page.limit, page.offset, scope, query)
    return Page[SourceRead](
        items=[SourceRead.model_validate(source) for source in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/compare")
async def compare_sources(
    request: SourceComparisonRequest, session: DatabaseSession, policy: Policy
) -> SourceComparisonRead:
    """Show 2 to 10 sources side by side, with what they have in common.

    Each source gets the same observed counts and dates as its provenance
    profile, in the order asked. The shared counts say how many event
    clusters, entities and claims two or more of the sources have in common.
    This is a description, not a judgement: sources are not scored or ranked.
    With authentication on, organization_id is required and every source must
    belong to it; sources of two organizations are never compared.
    """
    scope = await policy.scope(request.organization_id)
    comparison = await SourceComparisonService(session).compare(request.source_ids, scope)
    return SourceComparisonRead(
        sources=[
            ComparedSourceRead(
                source=SourceRead.model_validate(item.source),
                provenance=SourceProvenanceRead.model_validate(item.provenance),
            )
            for item in comparison.sources
        ],
        shared_event_cluster_count=comparison.shared_event_cluster_count,
        shared_entity_count=comparison.shared_entity_count,
        shared_claim_count=comparison.shared_claim_count,
    )


@router.get("/{source_id}")
async def get_source(source_id: uuid.UUID, policy: Policy) -> SourceRead:
    return SourceRead.model_validate(await policy.authorize_source(source_id))


@router.get("/{source_id}/provenance")
async def source_provenance(
    source_id: uuid.UUID, session: DatabaseSession, policy: Policy
) -> SourceProvenanceRead:
    """Counts and dates that SignalScope has observed for one source.

    These are provenance signals: how many documents, entities, claims and
    events came from the source, when, and how many of its events other
    sources also report. They are not a credibility score, and sources are
    not ranked against each other. Other sources only count when they belong
    to the same organization.
    """
    source = await policy.authorize_source(source_id)
    scope = policy.resource_scope(source.organization_id)
    profile = await SourceProvenanceService(session).profile(source_id, scope)
    return SourceProvenanceRead.model_validate(profile)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: uuid.UUID, sources: Sources, policy: Policy) -> None:
    await policy.authorize_source(source_id, ContentCapability.MANAGE)
    await sources.delete(source_id)


@router.put("/{source_id}/schedule")
async def schedule_source(
    source_id: uuid.UUID, data: SourceScheduleUpdate, schedules: Schedules, policy: Policy
) -> SourceRead:
    """Ingest a web or RSS source every interval_minutes, from start_at or from now."""
    await policy.authorize_source(source_id, ContentCapability.MANAGE)
    source = await schedules.enable(source_id, data.interval_minutes, data.start_at)
    return SourceRead.model_validate(source)


@router.delete("/{source_id}/schedule")
async def unschedule_source(
    source_id: uuid.UUID, schedules: Schedules, policy: Policy
) -> SourceRead:
    """Stop scheduled ingestion. The interval is kept."""
    await policy.authorize_source(source_id, ContentCapability.MANAGE)
    return SourceRead.model_validate(await schedules.disable(source_id))
