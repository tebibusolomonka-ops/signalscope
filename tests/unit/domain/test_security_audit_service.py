import uuid
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.audit.service import AuditAction, SecurityAuditService
from signalscope.domain.organizations.membership import OrganizationRole


class FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, item: Any) -> None:
        self.added.append(item)


def service() -> tuple[SecurityAuditService, FakeSession]:
    session = FakeSession()
    return SecurityAuditService(cast(AsyncSession, session)), session


def test_record_adds_to_the_session() -> None:
    audit, session = service()
    user_id = uuid.uuid4()

    event = audit.record(
        AuditAction.MEMBER_ADDED,
        actor_user_id=None,
        resource_type="organization",
        details={"user_id": user_id, "role": OrganizationRole.ADMIN},
    )

    assert session.added == [event]
    assert event.action == "organization.member_added"
    assert event.details == {"user_id": str(user_id), "role": "admin"}
    assert type(event.details["role"]) is str


@pytest.mark.parametrize("key", ["password", "token", "token_hash", "authorization", "email"])
def test_only_known_detail_keys(key: str) -> None:
    audit, session = service()

    with pytest.raises(ValueError, match=key):
        audit.record(
            AuditAction.LOGIN, actor_user_id=None, resource_type="user", details={key: "x"}
        )
    assert session.added == []


def test_action_names_are_short() -> None:
    assert all(len(action.value) <= 64 for action in AuditAction)


def test_failed_login_reason_is_allowed_without_identifier() -> None:
    audit, session = service()

    event = audit.record(
        AuditAction.LOGIN_FAILED,
        actor_user_id=None,
        resource_type="authentication",
        details={"reason": "invalid_credentials"},
    )

    assert session.added == [event]
    assert event.action == "authentication_login_failed"
    assert event.details == {"reason": "invalid_credentials"}
