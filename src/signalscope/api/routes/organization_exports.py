import uuid

from fastapi import APIRouter, Request, Response, status

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import Blobs, DatabaseSession
from signalscope.api.pagination import Pagination
from signalscope.domain.organizations.export_schemas import (
    OrganizationExportAssetsRead,
    OrganizationExportRead,
    OrganizationExportVerificationRead,
)
from signalscope.domain.organizations.export_service import OrganizationExportService

router = APIRouter(prefix="/organizations/{organization_id}/exports", tags=["Organizations"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_organization_export(
    organization_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
    blobs: Blobs,
    request: Request,
) -> OrganizationExportRead:
    settings = request.app.state.settings
    export = await OrganizationExportService(
        session,
        current.user,
        blobs,
        max_assets=settings.organization_export_max_assets,
        max_bytes=settings.organization_export_max_bytes,
    ).create(organization_id)
    return OrganizationExportRead.model_validate(export)


@router.get("")
async def list_organization_exports(
    organization_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
    page: Pagination,
) -> list[OrganizationExportRead]:
    exports = await OrganizationExportService(session, current.user).list(
        organization_id, page.limit, page.offset
    )
    return [OrganizationExportRead.model_validate(export) for export in exports]


@router.get("/assets")
async def get_organization_export_assets(
    organization_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
    request: Request,
) -> OrganizationExportAssetsRead:
    assets = await OrganizationExportService(session, current.user).assets(organization_id)
    settings = request.app.state.settings
    return OrganizationExportAssetsRead(
        asset_count=assets.asset_count,
        asset_bytes=assets.asset_bytes,
        max_assets=settings.organization_export_max_assets,
        max_bytes=settings.organization_export_max_bytes,
    )


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


@router.post("/{export_id}/verify")
async def verify_organization_export(
    organization_id: uuid.UUID,
    export_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
    blobs: Blobs,
) -> OrganizationExportVerificationRead:
    result = await OrganizationExportService(session, current.user, blobs).verify(
        organization_id, export_id
    )
    return OrganizationExportVerificationRead.build(result)
