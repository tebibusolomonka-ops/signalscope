"""Every ORM model, imported in one place so Base.metadata knows all tables.

Alembic and the database test setup import Base from here.
"""

from signalscope.db.base import Base
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.blobs.model import BlobCleanupTask
from signalscope.domain.claims.job import ClaimExtractionJob
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.extraction import DocumentExtraction
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.revision import DocumentRevision
from signalscope.domain.entities.job import EntityExtractionJob
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.evaluation.model import EvaluationReportRecord
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.job import EventExtractionJob
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.ingestion.model import IngestionJob, IngestionRun
from signalscope.domain.investigations.collaborator import InvestigationCollaborator
from signalscope.domain.investigations.item import InvestigationItem
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.operations.attempt import OperationAttempt
from signalscope.domain.organizations.backup_policy import OrganizationBackupPolicy
from signalscope.domain.organizations.drill_record import OrganizationDisasterRecoveryDrill
from signalscope.domain.organizations.export_record import OrganizationExport
from signalscope.domain.organizations.invitation import OrganizationInvitation
from signalscope.domain.organizations.membership import OrganizationMembership
from signalscope.domain.organizations.model import Organization
from signalscope.domain.organizations.restore_record import OrganizationRestore
from signalscope.domain.processing.model import DocumentProcessingJob
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.research.turn import ResearchTurn
from signalscope.domain.retention.model import OrganizationRetentionPolicy
from signalscope.domain.search.embedding_job import EmbeddingJob
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.sources.model import Source
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.model import User
from signalscope.domain.users.session import UserSession
from signalscope.domain.users.throttle import AuthenticationThrottle

__all__ = [
    "Base",
    "AuthenticationThrottle",
    "BlobCleanupTask",
    "ChunkEmbedding",
    "Claim",
    "ClaimEvidence",
    "ClaimExtractionJob",
    "Document",
    "DocumentAsset",
    "DocumentChunk",
    "DocumentExtraction",
    "DocumentProcessingJob",
    "DocumentRevision",
    "EmbeddingJob",
    "Entity",
    "EntityExtractionJob",
    "EntityMention",
    "EvaluationReportRecord",
    "Event",
    "EventCluster",
    "EventClusterMember",
    "EventEvidence",
    "EventExtractionJob",
    "IngestionJob",
    "IngestionRun",
    "Investigation",
    "InvestigationCollaborator",
    "InvestigationItem",
    "Organization",
    "OrganizationBackupPolicy",
    "OrganizationDisasterRecoveryDrill",
    "OrganizationExport",
    "OrganizationInvitation",
    "OrganizationMembership",
    "OrganizationRestore",
    "OperationAttempt",
    "OrganizationRetentionPolicy",
    "ResearchSession",
    "ResearchTurn",
    "SecurityAuditEvent",
    "Source",
    "User",
    "UserPasswordCredential",
    "UserSession",
]
