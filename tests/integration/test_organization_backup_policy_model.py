from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.organizations.backup_policy import (
    OrganizationBackupFrequency,
    OrganizationBackupPolicy,
)
from signalscope.domain.organizations.model import Organization
from tenancy_helpers import make_tenants

pytestmark = pytest.mark.anyio


async def save_policy(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: Any,
    **values: Any,
) -> OrganizationBackupPolicy:
    async with session_factory() as session:
        policy = OrganizationBackupPolicy(organization_id=organization_id, **values)
        session.add(policy)
        await session.commit()
    return policy


async def test_policy_fields_and_defaults(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    policy = await save_policy(session_factory, tenants.a.id)

    assert policy.enabled is False
    assert policy.frequency is OrganizationBackupFrequency.DAILY
    assert policy.retention_count == 7
    assert policy.include_assets is False
    assert policy.last_run_at is None
    assert policy.next_run_at is None
    assert policy.created_at is not None
    assert policy.updated_at >= policy.created_at


@pytest.mark.parametrize("frequency", list(OrganizationBackupFrequency))
async def test_valid_frequency(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    frequency: OrganizationBackupFrequency,
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    policy = await save_policy(session_factory, tenants.a.id, frequency=frequency)
    assert policy.frequency is frequency


@pytest.mark.parametrize("retention_count", [1, 7, 100])
async def test_valid_retention_count(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    retention_count: int,
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await save_policy(session_factory, tenants.a.id, retention_count=retention_count)


@pytest.mark.parametrize(
    "values",
    [
        {"frequency": "monthly"},
        {"retention_count": 0},
        {"retention_count": 101},
    ],
)
async def test_invalid_policy_is_rejected(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    values: dict[str, Any],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    async with session_factory() as session:
        session.add(OrganizationBackupPolicy(organization_id=tenants.a.id, **values))
        with pytest.raises((IntegrityError, LookupError)):
            await session.flush()


async def test_timestamps_may_be_set(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    now = datetime(2026, 10, 4, 12, tzinfo=UTC)
    policy = await save_policy(session_factory, tenants.a.id, last_run_at=now, next_run_at=now)
    assert (policy.last_run_at, policy.next_run_at) == (now, now)


async def test_one_policy_per_organization(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await save_policy(session_factory, tenants.a.id)
    async with session_factory() as session:
        session.add(OrganizationBackupPolicy(organization_id=tenants.a.id))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_organization_foreign_key_and_cascade(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    policy = await save_policy(session_factory, tenants.a.id)

    async with session_factory() as session:
        await session.execute(delete(Organization).where(Organization.id == tenants.a.id))
        await session.commit()
        assert await session.get(OrganizationBackupPolicy, policy.organization_id) is None
