import uuid

from fastapi import APIRouter, Request, status

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import Blobs, DatabaseSession
from signalscope.api.pagination import Pagination
from signalscope.domain.organizations.backup_administration import (
    OrganizationBackupAdministrationService,
)
from signalscope.domain.organizations.backup_schemas import (
    OrganizationBackupPolicyRead,
    OrganizationBackupPolicyUpdate,
)
from signalscope.domain.organizations.export_schemas import OrganizationExportRead

router = APIRouter(prefix="/organizations/{organization_id}", tags=["Organizations"])


@router.get("/backup-policy")
async def get_backup_policy(
    organization_id: uuid.UUID, current: CurrentSession, session: DatabaseSession
) -> OrganizationBackupPolicyRead:
    policy = await OrganizationBackupAdministrationService(session, current.user).get_policy(
        organization_id
    )
    return OrganizationBackupPolicyRead.model_validate(policy)


@router.put("/backup-policy")
async def update_backup_policy(
    organization_id: uuid.UUID,
    update: OrganizationBackupPolicyUpdate,
    current: CurrentSession,
    session: DatabaseSession,
) -> OrganizationBackupPolicyRead:
    policy = await OrganizationBackupAdministrationService(session, current.user).set_policy(
        organization_id, **update.model_dump()
    )
    return OrganizationBackupPolicyRead.model_validate(policy)


@router.post("/backups/run", status_code=status.HTTP_201_CREATED)
async def run_organization_backup(
    organization_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
    blobs: Blobs,
    request: Request,
) -> OrganizationExportRead:
    settings = request.app.state.settings
    export = await OrganizationBackupAdministrationService(
        session,
        current.user,
        blobs,
        max_assets=settings.organization_export_max_assets,
        max_bytes=settings.organization_export_max_bytes,
    ).run(organization_id)
    return OrganizationExportRead.model_validate(export)


@router.get("/backups")
async def list_organization_backups(
    organization_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
    page: Pagination,
) -> list[OrganizationExportRead]:
    exports = await OrganizationBackupAdministrationService(session, current.user).list(
        organization_id, page.limit, page.offset
    )
    return [OrganizationExportRead.model_validate(export) for export in exports]
