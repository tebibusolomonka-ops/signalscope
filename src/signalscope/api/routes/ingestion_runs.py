import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.api.tenancy import Policy, ReadScope
from signalscope.domain.ingestion.model import IngestionStatus
from signalscope.domain.ingestion.repository import IngestionRunFilters
from signalscope.domain.ingestion.schemas import IngestionRunCreate, IngestionRunRead
from signalscope.domain.ingestion.service import IngestionRunService
from signalscope.domain.sources.model import Source
from signalscope.domain.tenancy.policy import ContentCapability

# Status changes are left out on purpose. Ingestion code will make them, not API clients.
router = APIRouter(prefix="/ingestion-runs", tags=["Ingestion runs"])


def get_ingestion_run_service(session: DatabaseSession) -> IngestionRunService:
    return IngestionRunService(session)


async def get_ingestion_run_filters(
    policy: Policy,
    scope: ReadScope,
    source_id: uuid.UUID | None = None,
    status: IngestionStatus | None = None,
) -> IngestionRunFilters:
    if source_id is not None:
        await policy.authorize_source(source_id)
    return IngestionRunFilters(source_id=source_id, status=status, scope=scope)


Runs = Annotated[IngestionRunService, Depends(get_ingestion_run_service)]
Filters = Annotated[IngestionRunFilters, Depends(get_ingestion_run_filters)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_ingestion_run(
    data: IngestionRunCreate, runs: Runs, policy: Policy
) -> IngestionRunRead:
    """Ask for a source to be ingested. Needs the owner or admin role for its source."""
    await policy.authorize_source(data.source_id, ContentCapability.MANAGE)
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
async def get_ingestion_run(run_id: uuid.UUID, runs: Runs, policy: Policy) -> IngestionRunRead:
    run = await runs.get(run_id)
    source = await policy.session.get(Source, run.source_id)
    await policy.require_read(
        None if source is None else source.organization_id, "Ingestion run was not found."
    )
    return IngestionRunRead.model_validate(run)
