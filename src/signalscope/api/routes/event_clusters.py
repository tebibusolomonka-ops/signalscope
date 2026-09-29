import uuid

from fastapi import APIRouter

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.tenancy import ReadScope
from signalscope.domain.events.cluster_detail import EventClusterDetailService
from signalscope.domain.events.schemas import EventClusterDetailRead

router = APIRouter(prefix="/event-clusters", tags=["Timeline"])


@router.get("/{cluster_id}")
async def get_event_cluster(
    cluster_id: uuid.UUID, session: DatabaseSession, scope: ReadScope
) -> EventClusterDetailRead:
    """One cluster from the timeline, with its events and where each was reported.

    Read only. Clusters are formed by the exact event linker; there is no way
    to merge or split them here. With authentication on, only members and
    evidence of the organization_id organization are shown.
    """
    detail = await EventClusterDetailService(session).get(cluster_id, scope)
    return EventClusterDetailRead.model_validate(detail)
