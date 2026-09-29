"""FastAPI dependencies for organization content scope.

Routes that list or search content take an optional organization_id query
parameter and get a ContentScope from the policy. Routes for one resource
use the policy to check the organization stored on its source.
"""

import uuid
from typing import Annotated

from fastapi import Depends, Query

from signalscope.api.auth import Actor
from signalscope.api.dependencies import DatabaseSession
from signalscope.domain.tenancy.policy import ContentAccessPolicy, ContentCapability
from signalscope.domain.tenancy.scope import ContentScope


def content_policy(session: DatabaseSession, actor: Actor) -> ContentAccessPolicy:
    return ContentAccessPolicy(session, actor)


Policy = Annotated[ContentAccessPolicy, Depends(content_policy)]

OrganizationFilter = Annotated[
    uuid.UUID | None,
    Query(
        description=(
            "The organization whose content to use. Required when authentication is on, "
            "except for system admins, who then see legacy content only."
        )
    ),
]


async def read_scope(policy: Policy, organization_id: OrganizationFilter = None) -> ContentScope:
    return await policy.scope(organization_id, ContentCapability.READ)


ReadScope = Annotated[ContentScope, Depends(read_scope)]
