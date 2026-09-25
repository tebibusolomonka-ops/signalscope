import uuid
from datetime import UTC, datetime

from signalscope.domain.ingestion.model import IngestionRun, IngestionStatus
from signalscope.domain.ingestion.schemas import IngestionRunRead


def test_read_schema_includes_counters() -> None:
    now = datetime.now(UTC)
    run = IngestionRun(
        id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        status=IngestionStatus.COMPLETED,
        started_at=now,
        finished_at=now,
        error_message=None,
        items_seen=12,
        documents_created=10,
        duplicates_skipped=2,
        created_at=now,
        updated_at=now,
    )

    read = IngestionRunRead.model_validate(run)

    assert (read.items_seen, read.documents_created, read.duplicates_skipped) == (12, 10, 2)
