import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.domain.sources.scheduling import SourceScheduleService
from signalscope.domain.sources.schemas import SourceCreate, SourceRead, SourceScheduleUpdate
from signalscope.domain.sources.service import SourceService

router = APIRouter(prefix="/sources", tags=["Sources"])


def get_source_service(session: DatabaseSession) -> SourceService:
    return SourceService(session)


Sources = Annotated[SourceService, Depends(get_source_service)]


def get_source_schedule_service(session: DatabaseSession) -> SourceScheduleService:
    return SourceScheduleService(session)


Schedules = Annotated[SourceScheduleService, Depends(get_source_schedule_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_source(data: SourceCreate, sources: Sources) -> SourceRead:
    return SourceRead.model_validate(await sources.create(data))


@router.get("")
async def list_sources(page: Pagination, sources: Sources) -> Page[SourceRead]:
    items, total = await sources.list_page(page.limit, page.offset)
    return Page[SourceRead](
        items=[SourceRead.model_validate(source) for source in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{source_id}")
async def get_source(source_id: uuid.UUID, sources: Sources) -> SourceRead:
    return SourceRead.model_validate(await sources.get(source_id))


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: uuid.UUID, sources: Sources) -> None:
    await sources.delete(source_id)


@router.put("/{source_id}/schedule")
async def schedule_source(
    source_id: uuid.UUID, data: SourceScheduleUpdate, schedules: Schedules
) -> SourceRead:
    """Ingest a web or RSS source every interval_minutes, from start_at or from now."""
    source = await schedules.enable(source_id, data.interval_minutes, data.start_at)
    return SourceRead.model_validate(source)


@router.delete("/{source_id}/schedule")
async def unschedule_source(source_id: uuid.UUID, schedules: Schedules) -> SourceRead:
    """Stop scheduled ingestion. The interval is kept."""
    return SourceRead.model_validate(await schedules.disable(source_id))
