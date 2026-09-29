"""Two organizations with one user per role, for organization content tests.

Test passwords and tokens only.
"""

import uuid
from dataclasses import dataclass, field

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from signalscope.domain.organizations.membership import OrganizationRole
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.sources.model import Source, SourceType

ROLES = ("owner", "admin", "member", "viewer")


@dataclass
class Tenant:
    id: uuid.UUID
    # Bearer headers of this organization's users, by role.
    headers: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def query(self) -> str:
        return f"organization_id={self.id}"


@dataclass
class Tenants:
    a: Tenant
    b: Tenant
    system: dict[str, str]
    outsider: dict[str, str]


async def make_tenants(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> Tenants:
    """Organizations A and B, each with an owner, admin, member and viewer.

    Also a system admin and a user in no organization.
    """
    tenants = []
    for name in ("a", "b"):
        users = {
            role: await create_account(session_factory, f"{name}-{role}@example.org")
            for role in ROLES
        }
        async with session_factory() as session:
            service = OrganizationService(session)
            organization = await service.create(users["owner"], f"Org {name}", f"org-{name}")
            for role in ROLES[1:]:
                await service.add_member(
                    users["owner"], organization.id, users[role].id, OrganizationRole(role)
                )
        tenant = Tenant(organization.id)
        for role in ROLES:
            tenant.headers[role] = bearer(await login(client, f"{name}-{role}@example.org"))
        tenants.append(tenant)
    await create_account(session_factory, "system@example.org", system_admin=True)
    await create_account(session_factory, "outsider@example.org")
    return Tenants(
        a=tenants[0],
        b=tenants[1],
        system=bearer(await login(client, "system@example.org")),
        outsider=bearer(await login(client, "outsider@example.org")),
    )


async def add_source(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID | None,
    name: str = "Harbour feed",
) -> uuid.UUID:
    async with session_factory() as session:
        source = Source(
            type=SourceType.RSS,
            name=name,
            url="https://example.org/feed.xml",
            organization_id=organization_id,
        )
        session.add(source)
        await session.commit()
        return source.id
