"""Checks that a record saved in an investigation belongs to the investigation's organization."""

import uuid

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.model import Event
from signalscope.domain.events.repository import visible_events
from signalscope.domain.investigations.item import InvestigationItemType
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.sources.model import Source
from signalscope.domain.tenancy.scope import ContentScope


def _condition(
    item_type: InvestigationItemType, reference_id: uuid.UUID, scope: ContentScope
) -> ColumnElement[bool]:
    """True when the record exists and is in scope."""
    match item_type:
        case InvestigationItemType.SOURCE:
            return exists().where(
                Source.id == reference_id, scope.owner_condition(Source.organization_id)
            )
        case InvestigationItemType.DOCUMENT:
            return exists().where(
                Document.id == reference_id, scope.source_condition(Document.source_id)
            )
        case InvestigationItemType.EVENT:
            return exists().where(Event.id == reference_id, visible_events(scope, Event.id))
        case InvestigationItemType.EVENT_CLUSTER:
            return exists().where(
                EventCluster.id == reference_id,
                EventClusterMember.cluster_id == EventCluster.id,
                visible_events(scope, EventClusterMember.event_id),
            )
        case InvestigationItemType.ENTITY:
            # Shared rows: the entity must be mentioned in the organization's documents.
            return exists().where(
                Entity.id == reference_id,
                EntityMention.entity_id == Entity.id,
                scope.document_condition(EntityMention.document_id),
            )
        case InvestigationItemType.CLAIM:
            return exists().where(
                Claim.id == reference_id,
                ClaimEvidence.claim_id == Claim.id,
                scope.chunk_condition(ClaimEvidence.chunk_id),
            )
        case InvestigationItemType.RESEARCH_SESSION:
            return exists().where(
                ResearchSession.id == reference_id,
                scope.owner_condition(ResearchSession.organization_id),
            )


async def reference_in_scope(
    session: AsyncSession,
    item_type: InvestigationItemType,
    reference_id: uuid.UUID,
    scope: ContentScope,
) -> bool:
    """Whether the record may be saved in an investigation of this scope.

    With an organization scope the record must belong to that organization,
    so another organization's ID cannot be saved, even for a shared entity or
    claim. A legacy scope allows legacy records only.
    """
    return bool(await session.scalar(select(_condition(item_type, reference_id, scope))))
