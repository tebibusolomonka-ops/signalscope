"""Every ORM model, imported in one place so Base.metadata knows all tables.

Alembic and the database test setup import Base from here.
"""

from signalscope.db.base import Base
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.extraction import DocumentExtraction
from signalscope.domain.documents.model import Document
from signalscope.domain.ingestion.model import IngestionJob, IngestionRun
from signalscope.domain.sources.model import Source

__all__ = [
    "Base",
    "Document",
    "DocumentAsset",
    "DocumentExtraction",
    "IngestionJob",
    "IngestionRun",
    "Source",
]
