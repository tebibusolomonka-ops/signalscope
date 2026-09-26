"""Every ORM model, imported in one place so Base.metadata knows all tables.

Alembic and the database test setup import Base from here.
"""

from signalscope.db.base import Base
from signalscope.domain.blobs.model import BlobCleanupTask
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.extraction import DocumentExtraction
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.revision import DocumentRevision
from signalscope.domain.ingestion.model import IngestionJob, IngestionRun
from signalscope.domain.processing.model import DocumentProcessingJob
from signalscope.domain.sources.model import Source

__all__ = [
    "Base",
    "BlobCleanupTask",
    "Document",
    "DocumentAsset",
    "DocumentChunk",
    "DocumentExtraction",
    "DocumentProcessingJob",
    "DocumentRevision",
    "IngestionJob",
    "IngestionRun",
    "Source",
]
