import uuid
from dataclasses import dataclass, fields
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import NotFoundError
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.revision import DocumentRevision
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.investigations.collaborator import InvestigationCollaborator
from signalscope.domain.investigations.item import InvestigationItem
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.operations.attempt import OperationAttempt
from signalscope.domain.organizations.membership import OrganizationMembership
from signalscope.domain.organizations.model import Organization
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.research.turn import ResearchTurn
from signalscope.domain.sources.model import Source


@dataclass(frozen=True, slots=True)
class OrganizationExportInventory:
    organization: tuple[Organization, ...]
    memberships: tuple[OrganizationMembership, ...]
    sources: tuple[Source, ...]
    documents: tuple[Document, ...]
    document_revisions: tuple[DocumentRevision, ...]
    document_chunks: tuple[DocumentChunk, ...]
    document_assets: tuple[DocumentAsset, ...]
    entities: tuple[Entity, ...]
    entity_mentions: tuple[EntityMention, ...]
    claims: tuple[Claim, ...]
    claim_evidence: tuple[ClaimEvidence, ...]
    events: tuple[Event, ...]
    event_evidence: tuple[EventEvidence, ...]
    event_clusters: tuple[EventCluster, ...]
    event_cluster_members: tuple[EventClusterMember, ...]
    investigations: tuple[Investigation, ...]
    investigation_items: tuple[InvestigationItem, ...]
    investigation_collaborators: tuple[InvestigationCollaborator, ...]
    research_sessions: tuple[ResearchSession, ...]
    research_turns: tuple[ResearchTurn, ...]
    security_audit: tuple[SecurityAuditEvent, ...]
    operation_history: tuple[OperationAttempt, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {field.name: len(getattr(self, field.name)) for field in fields(self)}


class OrganizationExportInventoryService:
    """Collect a deterministic, tenant-scoped inventory for an export."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(self, organization_id: uuid.UUID) -> OrganizationExportInventory:
        organization = await self.session.get(Organization, organization_id)
        if organization is None:
            raise NotFoundError("Organization was not found.")

        tenant_document_ids = select(Document.id).where(
            Document.source_id.in_(
                select(Source.id).where(Source.organization_id == organization_id)
            )
        )
        tenant_documents = Document.id.in_(tenant_document_ids)
        tenant_chunk_ids = select(DocumentChunk.id).where(
            DocumentChunk.document_id.in_(tenant_document_ids)
        )
        tenant_chunks = DocumentChunk.id.in_(tenant_chunk_ids)
        tenant_investigation_ids = select(Investigation.id).where(
            Investigation.organization_id == organization_id
        )
        tenant_session_ids = select(ResearchSession.id).where(
            ResearchSession.organization_id == organization_id
        )
        tenant_entity_ids = select(EntityMention.entity_id).where(
            EntityMention.document_id.in_(tenant_document_ids)
        )
        tenant_claim_ids = select(ClaimEvidence.claim_id).where(
            ClaimEvidence.chunk_id.in_(tenant_chunk_ids)
        )
        tenant_event_ids = select(EventEvidence.event_id).where(
            EventEvidence.chunk_id.in_(tenant_chunk_ids)
        )
        tenant_cluster_ids = select(EventCluster.id).where(
            EventCluster.organization_id == organization_id
        )

        return OrganizationExportInventory(
            organization=(organization,),
            memberships=await self._rows(
                select(OrganizationMembership)
                .where(OrganizationMembership.organization_id == organization_id)
                .order_by(OrganizationMembership.user_id)
            ),
            sources=await self._rows(
                select(Source).where(Source.organization_id == organization_id).order_by(Source.id)
            ),
            documents=await self._rows(
                select(Document).where(tenant_documents).order_by(Document.id)
            ),
            document_revisions=await self._rows(
                select(DocumentRevision)
                .where(DocumentRevision.document_id.in_(tenant_document_ids))
                .order_by(DocumentRevision.document_id, DocumentRevision.version)
            ),
            document_chunks=await self._rows(
                select(DocumentChunk)
                .where(tenant_chunks)
                .order_by(DocumentChunk.document_id, DocumentChunk.position)
            ),
            document_assets=await self._rows(
                select(DocumentAsset)
                .where(DocumentAsset.document_id.in_(tenant_document_ids))
                .order_by(DocumentAsset.document_id, DocumentAsset.id)
            ),
            entities=await self._rows(
                select(Entity).where(Entity.id.in_(tenant_entity_ids)).order_by(Entity.id)
            ),
            entity_mentions=await self._rows(
                select(EntityMention)
                .where(EntityMention.document_id.in_(tenant_document_ids))
                .order_by(EntityMention.id)
            ),
            claims=await self._rows(
                select(Claim).where(Claim.id.in_(tenant_claim_ids)).order_by(Claim.id)
            ),
            claim_evidence=await self._rows(
                select(ClaimEvidence)
                .where(ClaimEvidence.chunk_id.in_(tenant_chunk_ids))
                .order_by(ClaimEvidence.id)
            ),
            events=await self._rows(
                select(Event).where(Event.id.in_(tenant_event_ids)).order_by(Event.id)
            ),
            event_evidence=await self._rows(
                select(EventEvidence)
                .where(EventEvidence.chunk_id.in_(tenant_chunk_ids))
                .order_by(EventEvidence.id)
            ),
            event_clusters=await self._rows(
                select(EventCluster)
                .where(EventCluster.organization_id == organization_id)
                .order_by(EventCluster.id)
            ),
            event_cluster_members=await self._rows(
                select(EventClusterMember)
                .where(EventClusterMember.cluster_id.in_(tenant_cluster_ids))
                .order_by(EventClusterMember.cluster_id, EventClusterMember.event_id)
            ),
            investigations=await self._rows(
                select(Investigation)
                .where(Investigation.organization_id == organization_id)
                .order_by(Investigation.id)
            ),
            investigation_items=await self._rows(
                select(InvestigationItem)
                .where(InvestigationItem.investigation_id.in_(tenant_investigation_ids))
                .order_by(InvestigationItem.id)
            ),
            investigation_collaborators=await self._rows(
                select(InvestigationCollaborator)
                .where(InvestigationCollaborator.investigation_id.in_(tenant_investigation_ids))
                .order_by(
                    InvestigationCollaborator.investigation_id,
                    InvestigationCollaborator.user_id,
                )
            ),
            research_sessions=await self._rows(
                select(ResearchSession)
                .where(ResearchSession.organization_id == organization_id)
                .order_by(ResearchSession.id)
            ),
            research_turns=await self._rows(
                select(ResearchTurn)
                .where(ResearchTurn.session_id.in_(tenant_session_ids))
                .order_by(ResearchTurn.session_id, ResearchTurn.sequence)
            ),
            security_audit=await self._rows(
                select(SecurityAuditEvent)
                .where(SecurityAuditEvent.organization_id == organization_id)
                .order_by(SecurityAuditEvent.created_at, SecurityAuditEvent.id)
            ),
            operation_history=await self._rows(
                select(OperationAttempt)
                .where(OperationAttempt.organization_id == organization_id)
                .order_by(OperationAttempt.created_at, OperationAttempt.id)
            ),
        )

    async def _rows(self, statement: Select[tuple[Any]]) -> tuple[Any, ...]:
        return tuple(await self.session.scalars(statement))
