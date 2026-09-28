import uuid

from fastapi import APIRouter, status

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.domain.investigations.model import InvestigationStatus
from signalscope.domain.investigations.schemas import (
    InvestigationCreate,
    InvestigationItemCreate,
    InvestigationItemRead,
    InvestigationRead,
    InvestigationUpdate,
)
from signalscope.domain.investigations.service import InvestigationService

router = APIRouter(prefix="/investigations", tags=["Investigations"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_investigation(
    request: InvestigationCreate, session: DatabaseSession
) -> InvestigationRead:
    """Start a saved investigation.

    There are no users yet, so every investigation is visible to everyone who
    can reach the API.
    """
    investigation = await InvestigationService(session).create(request.title, request.description)
    return InvestigationRead.model_validate(investigation)


@router.get("")
async def list_investigations(
    session: DatabaseSession, page: Pagination, status: InvestigationStatus | None = None
) -> Page[InvestigationRead]:
    """Investigations, newest first, optionally only open or only closed ones."""
    items, total = await InvestigationService(session).list_page(status, page.limit, page.offset)
    return Page[InvestigationRead](
        items=[InvestigationRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{investigation_id}")
async def get_investigation(
    investigation_id: uuid.UUID, session: DatabaseSession
) -> InvestigationRead:
    return InvestigationRead.model_validate(
        await InvestigationService(session).get(investigation_id)
    )


@router.patch("/{investigation_id}")
async def update_investigation(
    investigation_id: uuid.UUID, request: InvestigationUpdate, session: DatabaseSession
) -> InvestigationRead:
    """Change the title, description or status. Closing makes it read only."""
    investigation = await InvestigationService(session).update(
        investigation_id,
        title=request.title,
        description=request.description,
        clear_description="description" in request.model_fields_set and request.description is None,
        status=request.status,
    )
    return InvestigationRead.model_validate(investigation)


@router.delete("/{investigation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_investigation(investigation_id: uuid.UUID, session: DatabaseSession) -> None:
    """Delete an open investigation and its items. The saved records stay."""
    await InvestigationService(session).delete(investigation_id)


@router.post("/{investigation_id}/items", status_code=status.HTTP_201_CREATED)
async def add_investigation_item(
    investigation_id: uuid.UUID, request: InvestigationItemCreate, session: DatabaseSession
) -> InvestigationItemRead:
    """Save a reference to an existing record, with a small snapshot of it as it is now.

    The snapshot is kept as it was saved, even when the record changes or is
    deleted later.
    """
    item = await InvestigationService(session).add_item(
        investigation_id, request.item_type, request.reference_id, request.label
    )
    return InvestigationItemRead.model_validate(item)


@router.get("/{investigation_id}/items")
async def list_investigation_items(
    investigation_id: uuid.UUID, session: DatabaseSession
) -> list[InvestigationItemRead]:
    """The saved items, in the order they were saved."""
    items = await InvestigationService(session).list_items(investigation_id)
    return [InvestigationItemRead.model_validate(item) for item in items]


@router.delete("/{investigation_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_investigation_item(
    investigation_id: uuid.UUID, item_id: uuid.UUID, session: DatabaseSession
) -> None:
    await InvestigationService(session).remove_item(investigation_id, item_id)
