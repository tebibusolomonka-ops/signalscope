import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from signalscope.domain.organizations.backup_policy import (
    OrganizationBackupFrequency,
    OrganizationBackupPolicy,
)
from signalscope.domain.organizations.backup_scheduler import (
    BackupSchedulingResult,
    OrganizationBackupScheduler,
)
from signalscope.domain.organizations.export_record import (
    OrganizationExport,
    OrganizationExportStatus,
)
from signalscope.domain.organizations.model import Organization

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


class MemoryBlobs:
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes:
        return b""

    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool:
        return False


class State:
    def __init__(self, policies: list[OrganizationBackupPolicy]) -> None:
        self.policies = policies
        self.lock = asyncio.Lock()
        self.runs: list[uuid.UUID] = []


class FakeSession:
    def __init__(self, state: State) -> None:
        self.state = state
        self.locked = False

    async def __aenter__(self) -> "FakeSession":
        await self.state.lock.acquire()
        self.locked = True
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self.locked:
            self.state.lock.release()

    async def scalar(self, statement: Any) -> OrganizationBackupPolicy | None:
        due = [
            policy
            for policy in self.state.policies
            if policy.enabled and (policy.next_run_at is None or policy.next_run_at <= NOW)
        ]
        return min(
            due, key=lambda item: item.next_run_at or datetime.min.replace(tzinfo=UTC), default=None
        )

    async def get(self, model: Any, key: uuid.UUID) -> Organization:
        return Organization(
            id=key,
            name="Organization",
            slug=f"organization-{key}",
            created_by_user_id=USER_ID,
        )


class FakeFactory:
    def __init__(self, state: State, fail: bool = False) -> None:
        self.state = state
        self.fail = fail

    def __call__(self, session: Any) -> "FakeBackupService":
        return FakeBackupService(self.state, self.fail)


class FakeBackupService:
    def __init__(self, state: State, fail: bool) -> None:
        self.state = state
        self.fail = fail

    async def run(
        self, organization_id: uuid.UUID, requested_by_user_id: uuid.UUID
    ) -> OrganizationExport:
        assert requested_by_user_id == USER_ID
        self.state.runs.append(organization_id)
        policy = next(
            item for item in self.state.policies if item.organization_id == organization_id
        )
        policy.next_run_at = NOW + timedelta(days=1)
        return OrganizationExport(
            organization_id=organization_id,
            requested_by_user_id=requested_by_user_id,
            status=(
                OrganizationExportStatus.FAILED if self.fail else OrganizationExportStatus.COMPLETED
            ),
            format_version="2",
        )


def backup_policy(
    *, enabled: bool = True, next_run_at: datetime | None = None
) -> OrganizationBackupPolicy:
    return OrganizationBackupPolicy(
        organization_id=uuid.uuid4(),
        enabled=enabled,
        frequency=OrganizationBackupFrequency.DAILY,
        retention_count=7,
        include_assets=False,
        next_run_at=next_run_at,
    )


def scheduler(state: State, *, fail: bool = False) -> OrganizationBackupScheduler:
    return OrganizationBackupScheduler(
        lambda: FakeSession(state),  # type: ignore[arg-type]
        MemoryBlobs(),
        clock=lambda: NOW,
        service_factory=FakeFactory(state, fail),  # type: ignore[arg-type]
    )


@pytest.mark.anyio
async def test_due_policies_run_in_bounded_batches() -> None:
    policies = [backup_policy(next_run_at=NOW - timedelta(days=index)) for index in range(3)]
    state = State(policies)

    result = await scheduler(state).run_due(limit=2)

    assert result == BackupSchedulingResult(policies_considered=2, backups_completed=2)
    assert len(state.runs) == 2


@pytest.mark.anyio
async def test_disabled_and_future_policies_are_not_run() -> None:
    state = State(
        [backup_policy(enabled=False), backup_policy(next_run_at=NOW + timedelta(minutes=1))]
    )

    assert await scheduler(state).run_due(limit=10) == BackupSchedulingResult(0, 0)
    assert state.runs == []


@pytest.mark.anyio
async def test_failed_backup_is_counted_as_considered() -> None:
    state = State([backup_policy(next_run_at=NOW)])

    assert await scheduler(state, fail=True).run_due(limit=10) == BackupSchedulingResult(1, 0)


@pytest.mark.anyio
async def test_concurrent_schedulers_run_policy_once() -> None:
    state = State([backup_policy(next_run_at=NOW)])

    results = await asyncio.gather(
        scheduler(state).run_due(limit=1),
        scheduler(state).run_due(limit=1),
    )

    assert sum(result.backups_completed for result in results) == 1
    assert len(state.runs) == 1


@pytest.mark.anyio
async def test_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        await scheduler(State([])).run_due(limit=0)
