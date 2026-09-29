import uuid

from fastapi import APIRouter, Response, status

from signalscope.api.auth import Actor
from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.core.errors import InvalidInputError
from signalscope.core.exports import MARKDOWN_MEDIA_TYPE, ExportFormat
from signalscope.domain.investigations.export import (
    InvestigationExport,
    InvestigationExportService,
    investigation_markdown,
)
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

ORGANIZATION_NEEDS_AUTH = "organization_id can only be set when authentication is enabled."


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_investigation(
    request: InvestigationCreate, session: DatabaseSession, actor: Actor
) -> InvestigationRead:
    """Start a saved investigation.

    With authentication enabled, it needs a bearer token and the ID of an
    organization the user belongs to, and the user becomes its owner. With
    authentication disabled, investigations have no organization and are
    open to everyone who can reach the API.
    """
    if actor is None and request.organization_id is not None:
        raise InvalidInputError(ORGANIZATION_NEEDS_AUTH)
    investigation = await InvestigationService(session, actor).create(
        request.title, request.description, organization_id=request.organization_id
    )
    return InvestigationRead.model_validate(investigation)


@router.get("")
async def list_investigations(
    session: DatabaseSession,
    actor: Actor,
    page: Pagination,
    status: InvestigationStatus | None = None,
) -> Page[InvestigationRead]:
    """Investigations, newest first, optionally only open or only closed ones."""
    items, total = await InvestigationService(session, actor).list_page(
        status, page.limit, page.offset
    )
    return Page[InvestigationRead](
        items=[InvestigationRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{investigation_id}")
async def get_investigation(
    investigation_id: uuid.UUID, session: DatabaseSession, actor: Actor
) -> InvestigationRead:
    return InvestigationRead.model_validate(
        await InvestigationService(session, actor).get(investigation_id)
    )


@router.get(
    "/{investigation_id}/export",
    response_model=InvestigationExport,
    responses={200: {"content": {"text/markdown": {}}}},
)
async def export_investigation(
    investigation_id: uuid.UUID,
    session: DatabaseSession,
    actor: Actor,
    format: ExportFormat = ExportFormat.JSON,
) -> InvestigationExport | Response:
    """The investigation with every saved item, grouped by type.

    Items show the snapshot taken when they were saved, not live data, and say
    whether the record still exists. format=markdown returns a Markdown report.
    Nothing is written on the server.
    """
    await InvestigationService(session, actor).get(investigation_id)
    export = await InvestigationExportService(session).export(investigation_id)
    if format is ExportFormat.MARKDOWN:
        return Response(investigation_markdown(export), media_type=MARKDOWN_MEDIA_TYPE)
    return export


@router.patch("/{investigation_id}")
async def update_investigation(
    investigation_id: uuid.UUID,
    request: InvestigationUpdate,
    session: DatabaseSession,
    actor: Actor,
) -> InvestigationRead:
    """Change the title, description or status. Closing makes it read only."""
    investigation = await InvestigationService(session, actor).update(
        investigation_id,
        title=request.title,
        description=request.description,
        clear_description="description" in request.model_fields_set and request.description is None,
        status=request.status,
    )
    return InvestigationRead.model_validate(investigation)


@router.delete("/{investigation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_investigation(
    investigation_id: uuid.UUID, session: DatabaseSession, actor: Actor
) -> None:
    """Delete an open investigation and its items. The saved records stay."""
    await InvestigationService(session, actor).delete(investigation_id)


@router.post("/{investigation_id}/items", status_code=status.HTTP_201_CREATED)
async def add_investigation_item(
    investigation_id: uuid.UUID,
    request: InvestigationItemCreate,
    session: DatabaseSession,
    actor: Actor,
) -> InvestigationItemRead:
    """Save a reference to an existing record, with a small snapshot of it as it is now.

    The snapshot is kept as it was saved, even when the record changes or is
    deleted later.
    """
    item = await InvestigationService(session, actor).add_item(
        investigation_id, request.item_type, request.reference_id, request.label
    )
    return InvestigationItemRead.model_validate(item)


@router.get("/{investigation_id}/items")
async def list_investigation_items(
    investigation_id: uuid.UUID, session: DatabaseSession, actor: Actor
) -> list[InvestigationItemRead]:
    """The saved items, in the order they were saved."""
    items = await InvestigationService(session, actor).list_items(investigation_id)
    return [InvestigationItemRead.model_validate(item) for item in items]


@router.delete("/{investigation_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_investigation_item(
    investigation_id: uuid.UUID, item_id: uuid.UUID, session: DatabaseSession, actor: Actor
) -> None:
    await InvestigationService(session, actor).remove_item(investigation_id, item_id)


@router.post("/{investigation_id}/research-sessions/{session_id}")
async def save_research_session(
    investigation_id: uuid.UUID,
    session_id: uuid.UUID,
    session: DatabaseSession,
    actor: Actor,
    response: Response,
) -> InvestigationItemRead:
    """Save a research session in the investigation, with its title, mode, scope and turns so far.

    Answers 201 when it is saved now, and 200 with the earlier item when it was
    saved before. The snapshot is not updated by saving again.
    """
    item, created = await InvestigationService(session, actor).save_research_session(
        investigation_id, session_id
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return InvestigationItemRead.model_validate(item)
