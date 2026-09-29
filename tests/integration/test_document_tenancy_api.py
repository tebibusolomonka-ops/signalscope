import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.model import Document
from signalscope.domain.documents.revision import DocumentRevision
from tenancy_helpers import ROLES, Tenants, add_source, make_tenants

pytestmark = pytest.mark.anyio


class Content:
    source: dict[str, uuid.UUID]
    document: dict[str, uuid.UUID]


@pytest.fixture
async def tenants(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> Tenants:
    return await make_tenants(auth_client, session_factory)


@pytest.fixture
async def content(session_factory: async_sessionmaker[AsyncSession], tenants: Tenants) -> Content:
    """One source and one document with a revision for A, B and legacy content."""
    found = Content()
    found.source, found.document = {}, {}
    for key, organization_id in (("a", tenants.a.id), ("b", tenants.b.id), ("legacy", None)):
        found.source[key] = await add_source(session_factory, organization_id, f"{key} source")
        async with session_factory() as session:
            document = Document(
                source_id=found.source[key], title=f"{key}-only title", content="Harbour floods"
            )
            session.add(document)
            await session.flush()
            session.add(
                DocumentRevision(document_id=document.id, version=1, title=f"{key}-old title")
            )
            await session.commit()
            found.document[key] = document.id
    return found


async def test_lists_are_isolated(
    auth_client: httpx.AsyncClient, tenants: Tenants, content: Content
) -> None:
    a = tenants.a
    for role in ROLES:
        listed = await auth_client.get(f"/documents?{a.query}", headers=a.headers[role])
        assert [item["id"] for item in listed.json()["items"]] == [str(content.document["a"])]
        assert "b-only" not in listed.text and "legacy-only" not in listed.text

    by_b_source = await auth_client.get(
        f"/documents?{a.query}&source_id={content.source['b']}", headers=a.headers["owner"]
    )
    legacy = await auth_client.get("/documents", headers=tenants.system)
    system_b = await auth_client.get(f"/documents?{tenants.b.query}", headers=tenants.system)
    missing = await auth_client.get("/documents", headers=a.headers["owner"])

    assert by_b_source.status_code == 404
    assert [item["id"] for item in legacy.json()["items"]] == [str(content.document["legacy"])]
    assert [item["id"] for item in system_b.json()["items"]] == [str(content.document["b"])]
    assert missing.status_code == 422


async def test_one_document(
    auth_client: httpx.AsyncClient, tenants: Tenants, content: Content
) -> None:
    viewer = tenants.a.headers["viewer"]
    own = f"/documents/{content.document['a']}"

    assert (await auth_client.get(own, headers=viewer)).json()["title"] == "a-only title"
    revisions = await auth_client.get(f"{own}/revisions", headers=viewer)
    assert revisions.json()["items"][0]["version"] == 1
    revision = await auth_client.get(f"{own}/revisions/1", headers=viewer)
    assert revision.json()["title"] == "a-old title"

    for key in ("b", "legacy"):
        path = f"/documents/{content.document[key]}"
        for suffix in ("", "/revisions", "/revisions/1"):
            response = await auth_client.get(f"{path}{suffix}", headers=tenants.a.headers["owner"])
            assert response.status_code == 404
            assert f"{key}-only" not in response.text and f"{key}-old" not in response.text
    legacy_path = f"/documents/{content.document['legacy']}"
    assert (await auth_client.get(legacy_path, headers=tenants.system)).status_code == 200
    b_path = f"/documents/{content.document['b']}"
    assert (await auth_client.get(b_path, headers=tenants.outsider)).status_code == 404


async def test_create_and_delete_need_contribute(
    auth_client: httpx.AsyncClient, tenants: Tenants, content: Content
) -> None:
    a = tenants.a
    body = {"source_id": str(content.source["a"]), "title": "Note", "content": "Text"}

    by_viewer = await auth_client.post("/documents", json=body, headers=a.headers["viewer"])
    by_member = await auth_client.post("/documents", json=body, headers=a.headers["member"])
    into_b = await auth_client.post(
        "/documents",
        json=body | {"source_id": str(content.source["b"])},
        headers=a.headers["owner"],
    )
    delete_path = f"/documents/{content.document['a']}"
    viewer_delete = await auth_client.delete(delete_path, headers=a.headers["viewer"])
    b_delete = await auth_client.delete(
        f"/documents/{content.document['b']}", headers=a.headers["owner"]
    )
    member_delete = await auth_client.delete(delete_path, headers=a.headers["member"])

    assert (by_viewer.status_code, by_member.status_code, into_b.status_code) == (403, 201, 404)
    assert (viewer_delete.status_code, b_delete.status_code) == (403, 404)
    assert member_delete.status_code == 204
