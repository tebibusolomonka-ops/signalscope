import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.operations.access import operations_scope
from signalscope.domain.operations.attempt import (
    OperationAttempt,
    OperationAttemptOutcome,
    OperationAttemptQueue,
)
from signalscope.domain.tenancy.policy import ContentAccessPolicy


class OperationHistoryService:
    """Reads one organization's durable worker-attempt history."""

    def __init__(self, session: AsyncSession, policy: ContentAccessPolicy) -> None:
        self.session = session
        self.policy = policy

    async def list_page(
        self,
        organization_id: uuid.UUID,
        *,
        queue: OperationAttemptQueue | None = None,
        outcome: OperationAttemptOutcome | None = None,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[OperationAttempt], int]:
        await operations_scope(self.policy, organization_id)
        conditions = [OperationAttempt.organization_id == organization_id]
        for column, value in (
            (OperationAttempt.queue_name, queue),
            (OperationAttempt.outcome, outcome),
            (OperationAttempt.resource_type, resource_type),
            (OperationAttempt.resource_id, resource_id),
        ):
            if value is not None:
                conditions.append(column == value)
        if created_from is not None:
            conditions.append(OperationAttempt.created_at >= created_from)
        if created_to is not None:
            conditions.append(OperationAttempt.created_at <= created_to)
        query = select(OperationAttempt).where(*conditions)
        items = list(
            await self.session.scalars(
                query.order_by(OperationAttempt.created_at.desc(), OperationAttempt.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        total = await self.session.scalar(
            select(func.count()).select_from(OperationAttempt).where(*conditions)
        )
        return items, total or 0
