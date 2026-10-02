from signalscope.db.models import Base
from signalscope.domain.operations.attempt import (
    OperationAttempt,
    OperationAttemptOutcome,
    OperationAttemptQueue,
)


def test_operation_attempt_is_durable_tenant_history() -> None:
    table = OperationAttempt.__table__

    assert table.name in Base.metadata.tables
    assert [column.name for column in table.primary_key.columns] == ["id"]
    (organization_key,) = table.c.organization_id.foreign_keys
    assert organization_key.column.table.name == "organizations"
    assert organization_key.ondelete == "CASCADE"
    assert not table.c.job_id.foreign_keys
    assert not table.c.resource_id.foreign_keys
    assert "worker" not in {column.name for column in table.columns}


def test_operation_attempt_has_stable_queues_and_outcomes() -> None:
    assert {queue.value for queue in OperationAttemptQueue} == {
        "ingestion",
        "processing",
        "embedding",
        "entity",
        "event",
        "claim",
    }
    assert {outcome.value for outcome in OperationAttemptOutcome} == {
        "running",
        "succeeded",
        "failed",
        "recovered",
    }


def test_operation_attempt_indexes_support_tenant_history_queries() -> None:
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in OperationAttempt.__table__.indexes
    }

    assert indexes == {
        "ix_operation_attempts_job_id": ("job_id",),
        "ix_operation_attempts_organization_created_at": ("organization_id", "created_at"),
        "ix_operation_attempts_queue_name": ("queue_name",),
        "ix_operation_attempts_resource": ("resource_type", "resource_id"),
    }
