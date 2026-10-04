import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.organizations.archive_reader import OrganizationArchiveReader
from signalscope.domain.organizations.restore_conflicts import OrganizationRestoreConflictService
from signalscope.domain.organizations.restore_inventory import OrganizationRestoreInventoryService
from signalscope.domain.organizations.restore_user_mapping import (
    OrganizationRestoreUserMappingService,
)


async def build_restore_plan(
    session: AsyncSession, data: bytes, target_organization_id: uuid.UUID | None
) -> dict[str, Any]:
    """Build a verified, read-only organization restore plan."""
    archive = OrganizationArchiveReader().read(data)
    inventory = OrganizationRestoreInventoryService().build(archive)
    conflicts = await OrganizationRestoreConflictService(session).analyze(
        archive, target_organization_id
    )
    mapping = await OrganizationRestoreUserMappingService(session).plan(archive)
    return {
        "archive": {
            "format_version": archive.verification.format_version,
            "checked_files": archive.verification.checked_files,
            "checked_records": archive.verification.checked_records,
        },
        "inventory": {
            "counts": inventory.counts,
            "asset_count": inventory.asset_count,
            "referenced_user_ids": inventory.referenced_user_ids,
        },
        "conflicts": conflicts.conflicts,
        "warnings": conflicts.warnings,
        "unresolved_user_ids": conflicts.unresolved_user_ids,
        "user_mappings": [
            {
                "archived_user_id": str(item.archived_user_id),
                "role": item.role,
                "suggested_user_id": (
                    None if item.suggested_user_id is None else str(item.suggested_user_id)
                ),
                "suggested_email": item.suggested_email,
                "suggested_active": item.suggested_active,
            }
            for item in mapping.suggestions
        ],
    }
