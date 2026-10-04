import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.core.errors import InvalidInputError
from signalscope.domain.evaluation.import_service import EvaluationReportImportService
from signalscope.domain.evaluation.schemas import (
    EvaluationComparisonRequest,
    EvaluationReportDetailRead,
    EvaluationReportImportRequest,
    EvaluationReportSummaryRead,
)
from signalscope.domain.evaluation.service import EvaluationReportService
from signalscope.evaluation.comparison import compare_reports

router = APIRouter(prefix="/admin/evaluations", tags=["Evaluation administration"])


@router.get("")
async def list_evaluations(
    current: CurrentSession,
    session: DatabaseSession,
    page: Pagination,
    task: Annotated[str | None, Query(max_length=40)] = None,
    model: Annotated[str | None, Query(max_length=200)] = None,
    provider: Annotated[str | None, Query(max_length=200)] = None,
    dataset_fingerprint: Annotated[str | None, Query(max_length=128)] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Page[EvaluationReportSummaryRead]:
    """Stored evaluation reports, newest first. System admins only."""
    service = EvaluationReportService(session, current.user)
    items, total = await service.list_page(
        page.limit,
        page.offset,
        task=task,
        model=model,
        provider=provider,
        dataset_fingerprint=dataset_fingerprint,
        created_from=created_from,
        created_to=created_to,
    )
    return Page[EvaluationReportSummaryRead](
        items=[EvaluationReportSummaryRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_evaluation(
    request: EvaluationReportImportRequest, current: CurrentSession, session: DatabaseSession
) -> EvaluationReportDetailRead:
    """Store a measured evaluation report sent as JSON. Already-stored reports return as is."""
    EvaluationReportService(session, current.user)._require_admin()
    imported = await EvaluationReportImportService(session).import_report(
        request.report, imported_by_user_id=current.user.id
    )
    return EvaluationReportDetailRead.model_validate(imported.record)


@router.post("/compare")
async def compare_evaluations(
    request: EvaluationComparisonRequest, current: CurrentSession, session: DatabaseSession
) -> dict[str, Any]:
    """Factual metric differences between two or more stored reports of the same task.

    No winner or recommendation is returned. System admins only.
    """
    if len(request.report_ids) < 2:
        raise InvalidInputError("At least two reports are needed to compare.")
    records = await EvaluationReportService(session, current.user).get_many(request.report_ids)
    try:
        comparison = compare_reports(
            [record.report_json for record in records],
            [str(record.id) for record in records],
        )
    except ValueError as error:
        raise InvalidInputError(str(error)) from error
    return comparison.to_dict()


@router.get("/{report_id}")
async def get_evaluation(
    report_id: uuid.UUID, current: CurrentSession, session: DatabaseSession
) -> EvaluationReportDetailRead:
    record = await EvaluationReportService(session, current.user).get(report_id)
    return EvaluationReportDetailRead.model_validate(record)
