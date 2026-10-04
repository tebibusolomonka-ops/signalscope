from signalscope.db.models import Base
from signalscope.domain.evaluation.model import EVALUATION_TASKS, EvaluationReportRecord


def test_table_shape() -> None:
    table = EvaluationReportRecord.__table__
    assert table.name in Base.metadata.tables
    assert {column.name for column in table.columns} == {
        "id",
        "task",
        "model",
        "provider",
        "dataset_name",
        "dataset_fingerprint",
        "report_version",
        "report_json",
        "report_sha256",
        "environment_summary",
        "imported_by_user_id",
        "created_at",
    }


def test_known_tasks() -> None:
    assert EVALUATION_TASKS == (
        "embedding_retrieval",
        "reranking",
        "structured_extraction",
        "answer_citation",
        "relation_evaluation",
    )


def test_user_reference_is_optional_and_set_null() -> None:
    table = EvaluationReportRecord.__table__
    assert table.c.imported_by_user_id.nullable
    (foreign_key,) = table.c.imported_by_user_id.foreign_keys
    assert foreign_key.column.table.name == "users"
    assert foreign_key.ondelete == "SET NULL"


def test_report_hash_is_unique() -> None:
    indexes = {index.name: index for index in EvaluationReportRecord.__table__.indexes}
    assert indexes["uq_evaluation_report_records_report_sha256"].unique
