import uuid

from fastapi import APIRouter, Response, status

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import Blobs, DatabaseSession
from signalscope.domain.organizations.export_schemas import OrganizationExportRead
from signalscope.domain.organizations.export_service import OrganizationExportService

router = APIRouter(prefix="/organizations/{organization_id}/exports", tags=["Organizations"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_organization_export(
    organization_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
    blobs: Blobs,
) -> OrganizationExportRead:
    export = await OrganizationExportService(session, current.user, blobs).create(organization_id)
    return OrganizationExportRead.model_validate(export)


@router.get("")
async def list_organization_exports(
    organization_id: uuid.UUID, current: CurrentSession, session: DatabaseSession
) -> list[OrganizationExportRead]:
    exports = await OrganizationExportService(session, current.user).list(organization_id)
    return [OrganizationExportRead.model_validate(export) for export in exports]


@router.get("/{export_id}")
async def get_organization_export(
    organization_id: uuid.UUID,
    export_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
) -> OrganizationExportRead:
    export = await OrganizationExportService(session, current.user).get(organization_id, export_id)
    return OrganizationExportRead.model_validate(export)


@router.get("/{export_id}/download")
async def download_organization_export(
    organization_id: uuid.UUID,
    export_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
    blobs: Blobs,
) -> Response:
    data = await OrganizationExportService(session, current.user, blobs).download(
        organization_id, export_id
    )
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="organization-{organization_id}.zip"'
        },
    )
