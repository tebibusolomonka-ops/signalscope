from uuid import UUID

import pytest

from signalscope.domain.organizations.archive_reader import OrganizationArchive
from signalscope.domain.organizations.export_verification import OrganizationExportVerification
from signalscope.domain.organizations.model import Organization
from signalscope.domain.organizations.restore_conflicts import OrganizationRestoreConflictService

TARGET_ID = UUID("11111111-1111-1111-1111-111111111111")


class Session:
    def __init__(self, *, target: Organization | None = None, conflict: bool = False) -> None:
        self.target = target
        self.conflict = conflict

    async def get(self, _model: object, _id: UUID) -> Organization | None:
        return self.target

    async def scalar(self, _statement: object) -> UUID | None:
        return TARGET_ID if self.conflict else None

    async def scalars(self, _statement: object) -> list[UUID]:
        return []


def archive(sections: dict[str, tuple[dict[str, object], ...]]) -> OrganizationArchive:
    return OrganizationArchive({}, sections, OrganizationExportVerification(True, "2", 0, 0, ()))


@pytest.mark.anyio
async def test_empty_target_has_only_mapping_warning() -> None:
    target = Organization(
        id=TARGET_ID,
        name="Target",
        slug="target",
        created_by_user_id=TARGET_ID,
    )
    result = await OrganizationRestoreConflictService(Session(target=target)).analyze(
        archive({"memberships": ({"user_id": str(TARGET_ID)},)}), TARGET_ID
    )

    assert result.conflicts == ()
    assert result.unresolved_user_ids == (str(TARGET_ID),)


@pytest.mark.anyio
async def test_reports_non_empty_target_conflict() -> None:
    target = Organization(
        id=TARGET_ID,
        name="Target",
        slug="target",
        created_by_user_id=TARGET_ID,
    )
    result = await OrganizationRestoreConflictService(
        Session(target=target, conflict=True)
    ).analyze(archive({"sources": ({"id": str(TARGET_ID)},)}), TARGET_ID)

    assert result.conflicts == ("Target organization must be empty for restore.",)


@pytest.mark.anyio
async def test_new_target_reports_slug_conflict() -> None:
    result = await OrganizationRestoreConflictService(Session(conflict=True)).analyze(
        archive({"organization": ({"slug": "taken"},)})
    )

    assert result.conflicts == ("Organization slug already exists.",)
