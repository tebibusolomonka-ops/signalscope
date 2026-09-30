import uuid

from signalscope.core.errors import ServiceUnavailableError
from signalscope.domain.tenancy.policy import ContentAccessPolicy, ContentCapability
from signalscope.domain.tenancy.scope import ContentScope

AUTH_REQUIRED = "Operations need authentication to be enabled."


async def operations_scope(policy: ContentAccessPolicy, organization_id: uuid.UUID) -> ContentScope:
    """The one organization whose jobs the actor may operate on.

    Job errors and states are administrative, so this needs the owner or admin
    role there, or a system admin, who also names one organization. Without
    authentication there are no organizations, so operations are unavailable.
    """
    if policy.actor is None:
        raise ServiceUnavailableError(AUTH_REQUIRED)
    return await policy.scope(organization_id, ContentCapability.MANAGE)
