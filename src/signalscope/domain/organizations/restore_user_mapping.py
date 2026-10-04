import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import InvalidInputError
from signalscope.domain.organizations.archive_reader import OrganizationArchive
from signalscope.domain.users.model import User

# Archive fields that point at a user. Every referenced user must map to an
# existing active user before a restore may run.
USER_REFERENCES = (
    ("organization", "created_by_user_id"),
    ("memberships", "user_id"),
    ("investigations", "created_by_user_id"),
    ("investigation_collaborators", "user_id"),
    ("security_audit", "actor_user_id"),
)


@dataclass(frozen=True, slots=True)
class UserMappingSuggestion:
    """A referenced archived user and the existing user it could map to.

    The archive does not carry user emails, so a suggestion matches the
    archived user id to an existing user and surfaces that user's email and
    active state for the admin to confirm. It is never applied automatically.
    """

    archived_user_id: uuid.UUID
    role: str | None
    suggested_user_id: uuid.UUID | None
    suggested_email: str | None
    suggested_active: bool


@dataclass(frozen=True, slots=True)
class UserMappingPlan:
    suggestions: tuple[UserMappingSuggestion, ...]
    required_user_ids: tuple[uuid.UUID, ...]


class OrganizationRestoreUserMappingService:
    """Suggest and validate how archived users map to existing users."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def plan(self, archive: OrganizationArchive) -> UserMappingPlan:
        roles = _membership_roles(archive)
        required = referenced_user_ids(archive)
        suggestions: list[UserMappingSuggestion] = []
        for archived_id in required:
            user = await self.session.get(User, archived_id)
            suggestions.append(
                UserMappingSuggestion(
                    archived_user_id=archived_id,
                    role=roles.get(archived_id),
                    suggested_user_id=user.id if user is not None else None,
                    suggested_email=user.email if user is not None else None,
                    suggested_active=bool(user is not None and user.is_active),
                )
            )
        return UserMappingPlan(suggestions=tuple(suggestions), required_user_ids=required)

    async def resolve(
        self, archive: OrganizationArchive, mappings: Mapping[str, uuid.UUID]
    ) -> dict[uuid.UUID, uuid.UUID]:
        """Map every referenced archived user to an existing active user.

        A missing mapping defaults to the same user id. A mapping to a missing
        or inactive user, or two archived users mapped to one user, is refused.
        """
        resolved: dict[uuid.UUID, uuid.UUID] = {}
        used: set[uuid.UUID] = set()
        for archived_id in referenced_user_ids(archive):
            target_id = mappings.get(str(archived_id), archived_id)
            if target_id in used:
                raise InvalidInputError("Two archived users cannot map to the same user.")
            user = await self.session.get(User, target_id)
            if user is None or not user.is_active:
                raise InvalidInputError(
                    f"Archived user requires an active user mapping: {archived_id}"
                )
            resolved[archived_id] = target_id
            used.add(target_id)
        return resolved


def referenced_user_ids(archive: OrganizationArchive) -> tuple[uuid.UUID, ...]:
    values = {
        uuid.UUID(value)
        for section, key in USER_REFERENCES
        for row in archive.sections.get(section, ())
        if isinstance((value := row.get(key)), str)
    }
    return tuple(sorted(values))


def _membership_roles(archive: OrganizationArchive) -> dict[uuid.UUID, str]:
    roles: dict[uuid.UUID, str] = {}
    for row in archive.sections.get("memberships", ()):
        user_id = row.get("user_id")
        role = row.get("role")
        if isinstance(user_id, str) and isinstance(role, str):
            try:
                roles[uuid.UUID(user_id)] = role
            except ValueError:
                continue
    return roles
