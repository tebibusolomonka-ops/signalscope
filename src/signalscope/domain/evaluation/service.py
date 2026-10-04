import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ForbiddenError, NotFoundError
from signalscope.domain.evaluation.model import EvaluationReportRecord
from signalscope.domain.users.model import User

SYSTEM_ADMIN_REQUIRED = "Only system admins can review evaluation reports."


class EvaluationReportService:
    """Read access to stored evaluation reports, for system admins only."""

    def __init__(self, session: AsyncSession, actor: User | None) -> None:
        self.session = session
        self.actor = actor

    async def list_page(
        self,
        limit: int,
        offset: int,
        *,
        task: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        dataset_fingerprint: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> tuple[list[EvaluationReportRecord], int]:
        self._require_admin()
        conditions = self._conditions(
            task, model, provider, dataset_fingerprint, created_from, created_to
        )
        items = await self.session.scalars(
            select(EvaluationReportRecord)
            .where(*conditions)
            .order_by(EvaluationReportRecord.created_at.desc(), EvaluationReportRecord.id)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(EvaluationReportRecord).where(*conditions)
        )
        return list(items), total or 0

    async def get(self, report_id: uuid.UUID) -> EvaluationReportRecord:
        self._require_admin()
        record = await self.session.get(EvaluationReportRecord, report_id)
        if record is None:
            raise NotFoundError("Evaluation report was not found.")
        return record

    def _require_admin(self) -> None:
        if self.actor is not None and not (self.actor.is_system_admin and self.actor.is_active):
            raise ForbiddenError(SYSTEM_ADMIN_REQUIRED)

    @staticmethod
    def _conditions(
        task: str | None,
        model: str | None,
        provider: str | None,
        dataset_fingerprint: str | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if task is not None:
            conditions.append(EvaluationReportRecord.task == task)
        if model is not None:
            conditions.append(EvaluationReportRecord.model == model)
        if provider is not None:
            conditions.append(EvaluationReportRecord.provider == provider)
        if dataset_fingerprint is not None:
            conditions.append(EvaluationReportRecord.dataset_fingerprint == dataset_fingerprint)
        if created_from is not None:
            conditions.append(EvaluationReportRecord.created_at >= created_from)
        if created_to is not None:
            conditions.append(EvaluationReportRecord.created_at < created_to)
        return conditions
