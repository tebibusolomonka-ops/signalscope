import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from signalscope.domain.operations.queues import OperationsQueue, ResourceType


class OperationsOrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


class QueueSummaryRead(BaseModel):
    """Stored job states of one queue. Running includes jobs whose lease ran out."""

    model_config = ConfigDict(from_attributes=True)

    queue: OperationsQueue
    pending_count: int
    running_count: int
    failed_count: int
    # When the longest waiting pending job became available.
    oldest_pending_at: datetime | None
    # When the earliest job that is still failed finished.
    oldest_failed_at: datetime | None


class OperationsOverviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization: OperationsOrganizationRead
    queues: list[QueueSummaryRead]


class FailedJobRead(BaseModel):
    """A failed job. error is the short stored message, never a traceback."""

    model_config = ConfigDict(from_attributes=True)

    queue: OperationsQueue
    job_id: uuid.UUID
    status: str
    # What the job works on: a source, a document or a chunk.
    resource_type: ResourceType
    resource_id: uuid.UUID
    # Only for chunk jobs, which run one model.
    provider: str | None
    model: str | None
    attempt_count: int
    available_at: datetime
    created_at: datetime
    finished_at: datetime | None
    error: str | None
