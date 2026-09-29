import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tenancy_helpers import ROLES, Tenants, add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio

TEXT = "Harbour flood warning for the old town."
# Repeats the words, so B's chunks would rank above A's if they were searched.
STRONG = "Harbour flood warning. Harbour flood warning. Harbour flood warning."


@pytest.fixture
async def tenants(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> Tenants:
    return await make_tenants(auth_client, session_factory)


async def test_search_sees_one_organization(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    tenants: Tenants,
) -> None:
    a, b = tenants.a, tenants.b
    a_source = await add_source(session_factory, a.id, "Harbour feed")
    b_source = await add_source(session_factory, b.id, "Harbour feed")
    legacy_source = await add_source(session_factory, None, "Harbour feed")
    a_document, a_chunks = await add_document(session_factory, a_source, "a-doc", [TEXT] * 3)
    await add_document(session_factory, b_source, "b-doc", [STRONG] * 60)
    await add_document(session_factory, legacy_source, "legacy-doc", [STRONG] * 5)

    for role in ROLES:
        response = await auth_client.get(
            f"/search?q=harbour flood&limit=3&{a.query}", headers=a.headers[role]
        )
        items = response.json()["items"]
        # The limit is filled from A's chunks although B has many better matches.
        assert sorted(item["chunk_id"] for item in items) == sorted(str(c) for c in a_chunks)
        assert {item["document_id"] for item in items} == {str(a_document)}
        assert "b-doc" not in response.text and "legacy-doc" not in response.text

    b_view = await auth_client.get(f"/search?q=harbour&limit=50&{b.query}", headers=tenants.system)
    legacy = await auth_client.get("/search?q=harbour&limit=50", headers=tenants.system)
    assert len(b_view.json()["items"]) == 50
    assert {item["title"] for item in b_view.json()["items"]} == {"b-doc"}
    assert {item["title"] for item in legacy.json()["items"]} == {"legacy-doc"}


async def test_source_filter_and_errors(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    tenants: Tenants,
) -> None:
    a = tenants.a
    a_source = await add_source(session_factory, a.id)
    b_source = await add_source(session_factory, tenants.b.id)
    await add_document(session_factory, a_source, "a-doc", [TEXT])

    own = await auth_client.get(
        f"/search?q=harbour&source_id={a_source}&{a.query}", headers=a.headers["viewer"]
    )
    other = await auth_client.get(
        f"/search?q=harbour&source_id={b_source}&{a.query}", headers=a.headers["owner"]
    )
    wrong_organization = await auth_client.get(
        f"/search?q=harbour&{tenants.b.query}", headers=a.headers["owner"]
    )
    missing = await auth_client.get("/search?q=harbour", headers=a.headers["owner"])
    anonymous = await auth_client.get(f"/search?q=harbour&{a.query}")

    assert len(own.json()["items"]) == 1
    assert (other.status_code, wrong_organization.status_code) == (404, 404)
    assert (missing.status_code, anonymous.status_code) == (422, 401)


async def test_auth_disabled_searches_everything(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    legacy = await add_source(session_factory, None)
    await add_document(session_factory, legacy, "legacy-doc", [TEXT])

    response = await client.get("/search?q=harbour")

    assert [item["title"] for item in response.json()["items"]] == ["legacy-doc"]
