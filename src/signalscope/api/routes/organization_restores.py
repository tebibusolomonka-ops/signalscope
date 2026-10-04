import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Query

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import Blobs, DatabaseSession
from signalscope.core.errors import InvalidInputError
from signalscope.domain.organizations.restore_administration import (
    OrganizationRestoreAdministrationService,
)
from signalscope.domain.organizations.restore_schemas import OrganizationRestoreRead

router = APIRouter(prefix="/organizations", tags=["Organization restore"])


@router.post("/{organization_id}/restore")
async def apply_organization_restore(
    organization_id: uuid.UUID,
    archive: Annotated[bytes, Body(media_type="application/zip")],
    current: CurrentSession,
    session: DatabaseSession,
    blobs: Blobs,
    confirm: bool = False,
    user_mapping: Annotated[list[str] | None, Query()] = None,
) -> OrganizationRestoreRead:
    """Restore a verified archive into an empty organization. System admins only.

    The archive is re-verified here. A browser claim that it is already valid is
    not trusted. Each user_mapping is "archived_user_id:target_user_id".
    """
    service = OrganizationRestoreAdministrationService(session, current.user, blobs)
    restore = await service.apply(
        archive,
        organization_id,
        _parse_mappings(user_mapping or []),
        confirmed=confirm,
    )
    return OrganizationRestoreRead.model_validate(restore)


def _parse_mappings(pairs: list[str]) -> dict[str, uuid.UUID]:
    mappings: dict[str, uuid.UUID] = {}
    for pair in pairs:
        archived, separator, target = pair.partition(":")
        if not separator or not archived:
            raise InvalidInputError("Each user mapping must be 'archived_id:target_id'.")
        try:
            mappings[str(uuid.UUID(archived))] = uuid.UUID(target)
        except ValueError as error:
            raise InvalidInputError("A user mapping has an invalid id.") from error
    return mappings
