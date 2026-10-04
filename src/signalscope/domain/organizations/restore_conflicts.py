import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.model import Document
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.organizations.archive_reader import OrganizationArchive
from signalscope.domain.organizations.model import Organization
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.sources.model import Source
from signalscope.domain.users.model import User


@dataclass(frozen=True, slots=True)
class OrganizationRestoreConflicts:
    conflicts: tuple[str, ...]
    warnings: tuple[str, ...]
    unresolved_user_ids: tuple[str, ...]


class OrganizationRestoreConflictService:
    """Find restore conflicts without changing the target organization."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def analyze(
        self, archive: OrganizationArchive, target_organization_id: uuid.UUID | None = None
    ) -> OrganizationRestoreConflicts:
        conflicts: list[str] = []
        warnings: list[str] = []
        if target_organization_id is not None:
            target = await self.session.get(Organization, target_organization_id)
            if target is None:
                conflicts.append("Selected target organization does not exist.")
            else:
                await self._target_conflicts(archive, target.id, conflicts)
        else:
            await self._new_target_conflicts(archive, conflicts)
        unresolved = await self._unresolved_users(archive)
        if unresolved:
            warnings.append("Referenced users must be mapped to existing users.")
        if archive.sections.get("entities") or archive.sections.get("claims"):
            warnings.append("Canonical entities and claims are shared and are not duplicated.")
        if archive.sections.get("document_assets"):
            warnings.append("Assets require verified binary content before restore.")
        return OrganizationRestoreConflicts(
            conflicts=tuple(conflicts),
            warnings=tuple(warnings),
            unresolved_user_ids=unresolved,
        )

    async def _new_target_conflicts(
        self, archive: OrganizationArchive, conflicts: list[str]
    ) -> None:
        organization = _first(archive, "organization")
        if organization is None:
            conflicts.append("Archive has no organization record.")
            return
        slug = organization.get("slug")
        if isinstance(slug, str) and await self.session.scalar(
            select(Organization.id).where(Organization.slug == slug)
        ):
            conflicts.append("Organization slug already exists.")

    async def _target_conflicts(
        self, archive: OrganizationArchive, target_id: uuid.UUID, conflicts: list[str]
    ) -> None:
        checks = (
            ("sources", Source.id, "Source ID already exists."),
            ("documents", Document.id, "Document ID already exists."),
            ("investigations", Investigation.id, "Investigation ID already exists."),
            ("research_sessions", ResearchSession.id, "Research session ID already exists."),
            ("document_assets", DocumentAsset.id, "Asset ID already exists."),
        )
        for section, column, message in checks:
            ids = _ids(archive, section)
            if ids and await self.session.scalar(select(column).where(column.in_(ids)).limit(1)):
                conflicts.append(message)
        if (
            await self.session.scalar(
                select(Source.id).where(Source.organization_id == target_id).limit(1)
            )
            or await self.session.scalar(
                select(Investigation.id).where(Investigation.organization_id == target_id).limit(1)
            )
            or await self.session.scalar(
                select(ResearchSession.id)
                .where(ResearchSession.organization_id == target_id)
                .limit(1)
            )
        ):
            conflicts.append("Target organization must be empty for restore.")

    async def _unresolved_users(self, archive: OrganizationArchive) -> tuple[str, ...]:
        user_ids = {
            value
            for section in ("memberships", "investigation_collaborators")
            for row in archive.sections.get(section, ())
            if isinstance((value := row.get("user_id")), str)
        }
        if not user_ids:
            return ()
        parsed_ids: dict[str, uuid.UUID] = {}
        for value in user_ids:
            try:
                parsed_ids[value] = uuid.UUID(value)
            except ValueError:
                continue
        existing = set(
            await self.session.scalars(select(User.id).where(User.id.in_(parsed_ids.values())))
        )
        return tuple(sorted(value for value in user_ids if parsed_ids.get(value) not in existing))


def _first(archive: OrganizationArchive, section: str) -> dict[str, object] | None:
    rows = archive.sections.get(section, ())
    return rows[0] if rows else None


def _ids(archive: OrganizationArchive, section: str) -> tuple[uuid.UUID, ...]:
    values = []
    for row in archive.sections.get(section, ()):
        value = row.get("id")
        if isinstance(value, str):
            try:
                values.append(uuid.UUID(value))
            except ValueError:
                continue
    return tuple(values)
