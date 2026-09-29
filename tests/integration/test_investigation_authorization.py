import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from signalscope.domain.investigations.collaborator import (
    CollaboratorRole,
    InvestigationCollaborator,
)
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio

People = dict[str, tuple[User, dict[str, str]]]


@pytest.fixture
async def people(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> People:
    found = {}
    for name in ("owner", "editor", "viewer", "member", "outsider", "system"):
        email = f"{name}@example.org"
        user = await create_account(session_factory, email, system_admin=name == "system")
        found[name] = (user, bearer(await login(auth_client, email)))
    return found


@pytest.fixture
async def organization_id(auth_client: httpx.AsyncClient, people: People) -> str:
    response = await auth_client.post(
        "/organizations",
        json={"name": "Harbour Watch", "slug": "harbour-watch"},
        headers=people["owner"][1],
    )
    assert response.status_code == 201, response.text
    created: str = response.json()["id"]
    for name in ("editor", "viewer", "member"):
        added = await auth_client.post(
            f"/organizations/{created}/members",
            json={"user_id": str(people[name][0].id)},
            headers=people["owner"][1],
        )
        assert added.status_code == 201, added.text
    return created


async def collaborate(
    session_factory: async_sessionmaker[AsyncSession],
    investigation_id: str,
    user: User,
    role: CollaboratorRole,
) -> None:
    async with session_factory() as session:
        session.add(
            InvestigationCollaborator(
                investigation_id=uuid.UUID(investigation_id), user_id=user.id, role=role
            )
        )
        await session.commit()


async def create_shared(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    people: People,
    organization_id: str,
) -> str:
    response = await client.post(
        "/investigations",
        json={"title": "Floods", "organization_id": organization_id},
        headers=people["member"][1],
    )
    assert response.status_code == 201, response.text
    investigation_id: str = response.json()["id"]
    await collaborate(
        session_factory, investigation_id, people["editor"][0], CollaboratorRole.EDITOR
    )
    await collaborate(
        session_factory, investigation_id, people["viewer"][0], CollaboratorRole.VIEWER
    )
    return investigation_id


async def test_create_sets_owner(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    people: People,
    organization_id: str,
) -> None:
    member, headers = people["member"]

    created = await auth_client.post(
        "/investigations",
        json={"title": "Floods", "organization_id": organization_id},
        headers=headers,
    )
    missing = await auth_client.post("/investigations", json={"title": "Floods"}, headers=headers)
    not_a_member = await auth_client.post(
        "/investigations",
        json={"title": "Floods", "organization_id": organization_id},
        headers=people["outsider"][1],
    )
    no_token = await auth_client.post("/investigations", json={"title": "Floods"})

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["organization_id"] == organization_id
    assert body["created_by_user_id"] == str(member.id)
    async with session_factory() as session:
        roles = list(
            await session.execute(
                select(InvestigationCollaborator.user_id, InvestigationCollaborator.role).where(
                    InvestigationCollaborator.investigation_id == uuid.UUID(body["id"])
                )
            )
        )
    assert roles == [(member.id, CollaboratorRole.OWNER)]
    assert missing.status_code == 422
    assert not_a_member.status_code == 404
    assert no_token.status_code == 401


async def test_list_is_filtered(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    people: People,
    organization_id: str,
) -> None:
    shared = await create_shared(auth_client, session_factory, people, organization_id)
    private = await auth_client.post(
        "/investigations",
        json={"title": "Private", "organization_id": organization_id},
        headers=people["editor"][1],
    )
    assert private.status_code == 201
    async with session_factory() as session:
        session.add(Investigation(title="Legacy"))
        await session.commit()

    titles = {}
    for name in people:
        listed = await auth_client.get("/investigations", headers=people[name][1])
        titles[name] = sorted(item["title"] for item in listed.json()["items"])
        assert listed.json()["total"] == len(titles[name])

    assert titles == {
        "owner": ["Floods", "Private"],
        "editor": ["Floods", "Private"],
        "viewer": ["Floods"],
        "member": ["Floods"],
        "outsider": [],
        "system": ["Floods", "Legacy", "Private"],
    }
    detail = await auth_client.get(f"/investigations/{shared}", headers=people["outsider"][1])
    assert detail.status_code == 404


async def test_roles_on_one_investigation(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    people: People,
    organization_id: str,
) -> None:
    investigation_id = await create_shared(auth_client, session_factory, people, organization_id)
    path = f"/investigations/{investigation_id}"
    item = {"item_type": "event", "reference_id": str(uuid.uuid4())}
    research = f"{path}/research-sessions/{uuid.uuid4()}"

    def as_(name: str) -> dict[str, str]:
        return people[name][1]

    checks = {
        "viewer reads": await auth_client.get(path, headers=as_("viewer")),
        "viewer lists items": await auth_client.get(f"{path}/items", headers=as_("viewer")),
        "viewer exports": await auth_client.get(f"{path}/export", headers=as_("viewer")),
        "viewer edits": await auth_client.patch(path, json={"title": "X"}, headers=as_("viewer")),
        "viewer adds item": await auth_client.post(
            f"{path}/items", json=item, headers=as_("viewer")
        ),
        "viewer saves research": await auth_client.post(research, headers=as_("viewer")),
        "editor edits": await auth_client.patch(path, json={"title": "Y"}, headers=as_("editor")),
        # The event does not exist, so passing the check gives 404.
        "editor adds item": await auth_client.post(
            f"{path}/items", json=item, headers=as_("editor")
        ),
        "editor saves research": await auth_client.post(research, headers=as_("editor")),
        "editor deletes": await auth_client.delete(path, headers=as_("editor")),
        "outsider exports": await auth_client.get(f"{path}/export", headers=as_("outsider")),
        "organization owner edits": await auth_client.patch(
            path, json={"description": "Notes"}, headers=as_("owner")
        ),
    }

    assert {name: response.status_code for name, response in checks.items()} == {
        "viewer reads": 200,
        "viewer lists items": 200,
        "viewer exports": 200,
        "viewer edits": 403,
        "viewer adds item": 403,
        "viewer saves research": 403,
        "editor edits": 200,
        "editor adds item": 404,
        "editor saves research": 404,
        "editor deletes": 403,
        "outsider exports": 404,
        "organization owner edits": 200,
    }
    deleted = await auth_client.delete(path, headers=as_("member"))
    assert deleted.status_code == 204


async def test_legacy_investigations_are_for_system_admins(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    people: People,
    organization_id: str,
) -> None:
    async with session_factory() as session:
        legacy = Investigation(title="Legacy")
        session.add(legacy)
        await session.commit()
    path = f"/investigations/{legacy.id}"

    by_owner = await auth_client.get(path, headers=people["owner"][1])
    by_admin = await auth_client.patch(path, json={"title": "Old"}, headers=people["system"][1])

    assert by_owner.status_code == 404
    assert by_admin.status_code == 200, by_admin.text
    assert by_admin.json()["organization_id"] is None
