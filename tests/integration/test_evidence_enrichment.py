import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import report_event
from tenancy_helpers import Tenants, add_document, add_findings, add_source, make_tenants

pytestmark = pytest.mark.anyio


async def test_entity_and_claim_evidence_carry_document_and_source(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a
    source = await add_source(session_factory, a.id, "Harbour feed")
    _document, [chunk] = await add_document(
        session_factory, source, "Storm report", ["Porto flooded."]
    )
    entity_id, claim_id = await add_findings(session_factory, chunk)

    entity = await auth_client.get(f"/entities/{entity_id}?{a.query}", headers=a.headers["viewer"])
    claim = await auth_client.get(f"/claims/{claim_id}?{a.query}", headers=a.headers["viewer"])

    mention = entity.json()["mentions"][0]
    assert mention["document_title"] == "Storm report"
    assert mention["source_id"] == str(source)
    assert mention["source_name"] == "Harbour feed"
    evidence = claim.json()["evidence"][0]
    assert evidence["document_title"] == "Storm report"
    assert evidence["source_name"] == "Harbour feed"


async def test_event_evidence_carries_document_and_source(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a
    source = await add_source(session_factory, a.id, "Harbour feed")
    event_id = await report_event(session_factory, source, "Harbour flood")

    event = await auth_client.get(f"/events/{event_id}?{a.query}", headers=a.headers["viewer"])

    row = event.json()["evidence"][0]
    assert row["document_title"] == "Harbour flood"
    assert row["source_id"] == str(source)
    assert row["source_name"] == "Harbour feed"


async def test_enrichment_shows_only_the_requesting_organization(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b
    a_source = await add_source(session_factory, a.id, "Harbour feed")
    _a_doc, [a_chunk] = await add_document(session_factory, a_source, "Harbour doc", ["Porto a."])
    # Same shared entity, mentioned in both organizations' documents.
    entity_id, _ = await add_findings(session_factory, a_chunk, claim_text=None)
    b_source = await add_source(session_factory, b.id, "River feed")
    _b_doc, [b_chunk] = await add_document(session_factory, b_source, "River doc", ["Porto b."])
    await add_findings(session_factory, b_chunk, claim_text=None)

    seen = await auth_client.get(f"/entities/{entity_id}?{a.query}", headers=a.headers["viewer"])

    names = {mention["source_name"] for mention in seen.json()["mentions"]}
    assert names == {"Harbour feed"}
    assert "River feed" not in seen.text
