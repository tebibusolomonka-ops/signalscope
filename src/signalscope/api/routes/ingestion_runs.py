import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.domain.ingestion.model import IngestionStatus
from signalscope.domain.ingestion.repository import IngestionRunFilters
from signalscope.domain.ingestion.schemas import IngestionRunCreate, IngestionRunRead
from signalscope.domain.ingestion.service import IngestionRunService

# Status changes are left out on purpose. Ingestion code will make them, not API clients.
router = APIRouter(prefix="/ingestion-runs", tags=["Ingestion runs"])


def get_ingestion_run_service(session: DatabaseSession) -> IngestionRunService:
    return IngestionRunService(session)


def get_ingestion_run_filters(
    source_id: uuid.UUID | None = None, status: IngestionStatus | None = None
) -> IngestionRunFilters:
    return IngestionRunFilters(source_id=source_id, status=status)


Runs = Annotated[IngestionRunService, Depends(get_ingestion_run_service)]
Filters = Annotated[IngestionRunFilters, Depends(get_ingestion_run_filters)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_ingestion_run(data: IngestionRunCreate, runs: Runs) -> IngestionRunRead:
    return IngestionRunRead.model_validate(await runs.create(data.source_id))


@router.get("")
async def list_ingestion_runs(
    filters: Filters, page: Pagination, runs: Runs
) -> Page[IngestionRunRead]:
    items, total = await runs.list_page(filters, page.limit, page.offset)
    return Page[IngestionRunRead](
        items=[IngestionRunRead.model_validate(run) for run in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{run_id}")
async def get_ingestion_run(run_id: uuid.UUID, runs: Runs) -> IngestionRunRead:
    return IngestionRunRead.model_validate(await runs.get(run_id))
