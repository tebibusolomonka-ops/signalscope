import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.domain.sources.schemas import SourceCreate, SourceRead
from signalscope.domain.sources.service import SourceService

router = APIRouter(prefix="/sources", tags=["Sources"])


def get_source_service(session: DatabaseSession) -> SourceService:
    return SourceService(session)


Sources = Annotated[SourceService, Depends(get_source_service)]


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
