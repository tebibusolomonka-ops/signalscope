import uuid

import pytest

from signalscope.core.errors import InvalidInputError
from signalscope.domain.organizations.archive_reader import OrganizationArchive
from signalscope.domain.organizations.export_verification import OrganizationExportVerification
from signalscope.domain.organizations.restore_user_mapping import (
    OrganizationRestoreUserMappingService,
    referenced_user_ids,
)

OWNER = uuid.UUID("11111111-1111-1111-1111-111111111111")
MEMBER = uuid.UUID("22222222-2222-2222-2222-222222222222")
REPLACEMENT = uuid.UUID("33333333-3333-3333-3333-333333333333")

pytestmark = pytest.mark.anyio


class FakeUser:
    def __init__(self, user_id: uuid.UUID, *, email: str, is_active: bool = True) -> None:
        self.id = user_id
        self.email = email
        self.is_active = is_active


class FakeSession:
    def __init__(self, users: dict[uuid.UUID, FakeUser]) -> None:
        self.users = users

    async def get(self, _model: object, user_id: uuid.UUID) -> FakeUser | None:
        return self.users.get(user_id)


def archive(sections: dict[str, tuple[dict[str, object], ...]]) -> OrganizationArchive:
    return OrganizationArchive({}, sections, OrganizationExportVerification(True, "2", 0, 0, ()))


def membership_archive() -> OrganizationArchive:
    return archive(
        {
            "memberships": (
                {"user_id": str(OWNER), "role": "owner"},
                {"user_id": str(MEMBER), "role": "member"},
            )
        }
    )


def test_referenced_user_ids_are_sorted_and_unique() -> None:
    result = referenced_user_ids(
        archive(
            {
                "memberships": ({"user_id": str(MEMBER)}, {"user_id": str(OWNER)}),
                "security_audit": ({"actor_user_id": str(OWNER)}, {"actor_user_id": None}),
            }
        )
    )

    assert result == (OWNER, MEMBER)


async def test_plan_suggests_existing_users_with_email_and_role() -> None:
    session = FakeSession(
        {
            OWNER: FakeUser(OWNER, email="owner@example.org"),
            MEMBER: FakeUser(MEMBER, email="member@example.org", is_active=False),
        }
    )

    plan = await OrganizationRestoreUserMappingService(session).plan(membership_archive())

    suggestions = {item.archived_user_id: item for item in plan.suggestions}
    assert plan.required_user_ids == (OWNER, MEMBER)
    assert suggestions[OWNER].suggested_user_id == OWNER
    assert suggestions[OWNER].suggested_email == "owner@example.org"
    assert suggestions[OWNER].role == "owner"
    assert suggestions[OWNER].suggested_active is True
    assert suggestions[MEMBER].suggested_active is False
    assert suggestions[MEMBER].role == "member"


async def test_plan_marks_unknown_archived_user() -> None:
    session = FakeSession({OWNER: FakeUser(OWNER, email="owner@example.org")})

    plan = await OrganizationRestoreUserMappingService(session).plan(membership_archive())

    missing = next(item for item in plan.suggestions if item.archived_user_id == MEMBER)
    assert missing.suggested_user_id is None
    assert missing.suggested_email is None
    assert missing.suggested_active is False


async def test_resolve_defaults_to_same_active_user() -> None:
    session = FakeSession(
        {
            OWNER: FakeUser(OWNER, email="owner@example.org"),
            MEMBER: FakeUser(MEMBER, email="member@example.org"),
        }
    )

    resolved = await OrganizationRestoreUserMappingService(session).resolve(
        membership_archive(), {}
    )

    assert resolved == {OWNER: OWNER, MEMBER: MEMBER}


async def test_resolve_applies_explicit_mapping() -> None:
    session = FakeSession(
        {
            OWNER: FakeUser(OWNER, email="owner@example.org"),
            REPLACEMENT: FakeUser(REPLACEMENT, email="new@example.org"),
        }
    )

    resolved = await OrganizationRestoreUserMappingService(session).resolve(
        archive({"memberships": ({"user_id": str(MEMBER), "role": "member"},)}),
        {str(MEMBER): REPLACEMENT, str(OWNER): OWNER},
    )

    assert resolved == {MEMBER: REPLACEMENT}


async def test_resolve_refuses_missing_mapping() -> None:
    session = FakeSession({OWNER: FakeUser(OWNER, email="owner@example.org")})

    with pytest.raises(InvalidInputError, match="active user mapping"):
        await OrganizationRestoreUserMappingService(session).resolve(membership_archive(), {})


async def test_resolve_refuses_inactive_user() -> None:
    session = FakeSession({OWNER: FakeUser(OWNER, email="owner@example.org", is_active=False)})

    with pytest.raises(InvalidInputError, match="active user mapping"):
        await OrganizationRestoreUserMappingService(session).resolve(
            archive({"memberships": ({"user_id": str(OWNER), "role": "owner"},)}), {}
        )


async def test_resolve_refuses_duplicate_targets() -> None:
    session = FakeSession({REPLACEMENT: FakeUser(REPLACEMENT, email="new@example.org")})

    with pytest.raises(InvalidInputError, match="same user"):
        await OrganizationRestoreUserMappingService(session).resolve(
            membership_archive(),
            {str(OWNER): REPLACEMENT, str(MEMBER): REPLACEMENT},
        )
