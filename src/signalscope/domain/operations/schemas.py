import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from signalscope.domain.operations.queues import OperationsQueue


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
