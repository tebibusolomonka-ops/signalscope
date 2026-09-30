from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement

from signalscope.domain.claims.job import ClaimExtractionJob, ClaimExtractionJobStatus
from signalscope.domain.entities.job import EntityExtractionJob, EntityExtractionJobStatus
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.ingestion.model import IngestionJob, IngestionJobStatus
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.tenancy.scope import ContentScope


class OperationsQueue(StrEnum):
    """The job queues an organization's owners and admins can look at."""

    INGESTION = "ingestion"
    PROCESSING = "processing"
    EMBEDDING = "embedding"
    ENTITY_EXTRACTION = "entity_extraction"
    EVENT_EXTRACTION = "event_extraction"
    CLAIM_EXTRACTION = "claim_extraction"


class ResourceType(StrEnum):
    """What a job works on, which is also how it belongs to an organization."""

    SOURCE = "source"
    DOCUMENT = "document"
    CHUNK = "chunk"


@dataclass(frozen=True, slots=True)
class QueueTable:
    """One job table, the record it points at, and its status values.

    The six tables have the same status names and timing columns, but their
    classes and status enums differ, so each is described here instead of
    sharing a base class.
    """

    queue: OperationsQueue
    model: Any
    statuses: Any
    resource_type: ResourceType
    resource_column: str

    @property
    def resource_id(self) -> Any:
        return getattr(self.model, self.resource_column)

    def status(self, name: str) -> Any:
        return self.statuses(name)

    def in_scope(self, scope: ContentScope) -> ColumnElement[bool]:
        """Jobs whose record belongs to the scope, through its source."""
        if self.resource_type is ResourceType.SOURCE:
            return scope.source_condition(self.resource_id)
        if self.resource_type is ResourceType.DOCUMENT:
            return scope.document_condition(self.resource_id)
        return scope.chunk_condition(self.resource_id)


QUEUE_TABLES: dict[OperationsQueue, QueueTable] = {
    table.queue: table
    for table in (
        QueueTable(
            OperationsQueue.INGESTION,
            IngestionJob,
            IngestionJobStatus,
            ResourceType.SOURCE,
            "source_id",
        ),
        QueueTable(
            OperationsQueue.PROCESSING,
            DocumentProcessingJob,
            ProcessingJobStatus,
            ResourceType.DOCUMENT,
            "document_id",
        ),
        QueueTable(
            OperationsQueue.EMBEDDING,
            EmbeddingJob,
            EmbeddingJobStatus,
            ResourceType.CHUNK,
            "chunk_id",
        ),
        QueueTable(
            OperationsQueue.ENTITY_EXTRACTION,
            EntityExtractionJob,
            EntityExtractionJobStatus,
            ResourceType.CHUNK,
            "chunk_id",
        ),
        QueueTable(
            OperationsQueue.EVENT_EXTRACTION,
            EventExtractionJob,
            EventExtractionJobStatus,
            ResourceType.CHUNK,
            "chunk_id",
        ),
        QueueTable(
            OperationsQueue.CLAIM_EXTRACTION,
            ClaimExtractionJob,
            ClaimExtractionJobStatus,
            ResourceType.CHUNK,
            "chunk_id",
        ),
    )
}
