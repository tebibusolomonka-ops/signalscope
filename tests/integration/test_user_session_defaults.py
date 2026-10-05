import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.users.session import UserSession
from tenancy_helpers import make_tenants

pytestmark = pytest.mark.anyio


async def test_new_session_initializes_activity_timestamps(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    token_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()

    async with session_factory() as session:
        record = UserSession(
            user_id=tenants.a.owner_id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        session.add(record)
        await session.commit()
        session_id = record.id

    async with session_factory() as session:
        stored = await session.get(UserSession, session_id)

    assert stored is not None
    assert stored.created_at is not None
    assert stored.last_seen_at is not None
    assert stored.revoked_at is None
