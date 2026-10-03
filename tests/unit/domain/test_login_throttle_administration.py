from unittest.mock import AsyncMock, Mock

import pytest

from signalscope.core.errors import ForbiddenError, NotFoundError
from signalscope.domain.users.throttle_administration import (
    LoginThrottleAdministrationService,
    valid_throttle_identifier,
)

pytestmark = pytest.mark.anyio


def test_identifier_validation() -> None:
    assert valid_throttle_identifier("a" * 64)
    assert not valid_throttle_identifier("A" * 64)
    assert not valid_throttle_identifier("a" * 63)


async def test_normal_user_cannot_list_or_clear() -> None:
    actor = Mock(is_system_admin=False, is_active=True)
    service = LoginThrottleAdministrationService(AsyncMock(), actor)

    with pytest.raises(ForbiddenError):
        await service.list_throttles()
    with pytest.raises(ForbiddenError):
        await service.clear("a" * 64)


async def test_invalid_identifier_is_not_found_for_admin() -> None:
    actor = Mock(is_system_admin=True, is_active=True)
    service = LoginThrottleAdministrationService(AsyncMock(), actor)

    with pytest.raises(NotFoundError):
        await service.clear("not-an-identifier")
