"""Research sessions over HTTP, with a fake answer model that records what it is given."""

import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from fake_answers import FakeAnswerGenerator
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def generator() -> FakeAnswerGenerator:
    return FakeAnswerGenerator()


@pytest.fixture
async def answering_client(
    migrated_database: Settings, generator: FakeAnswerGenerator
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_database)
    app.state.answer_generators.register(generator)
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
async def library(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID]:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    await report_event(session_factory, wire, "Harbour flood")
    await report_event(session_factory, paper, "Bridge closed")
    return {"wire": wire, "paper": paper}


async def create(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    response = await client.post("/research/sessions", json={"retrieval_mode": "lexical"} | body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def ask(client: httpx.AsyncClient, session_id: str, question: str) -> dict[str, Any]:
    response = await client.post(
        f"/research/sessions/{session_id}/turns", json={"question": question}
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def test_conversation(
    answering_client: httpx.AsyncClient,
    library: dict[str, uuid.UUID],
    generator: FakeAnswerGenerator,
) -> None:
    research = await create(answering_client, title="Harbour")
    assert (research["title"], research["retrieval_mode"], research["source_id"]) == (
        "Harbour",
        "lexical",
        None,
    )

    first = await ask(answering_client, research["id"], "harbour flood")
    second = await ask(answering_client, research["id"], "bridge closed")

    assert first["session"]["id"] == research["id"]
    assert (first["turn"]["sequence"], second["turn"]["sequence"]) == (1, 2)
    turn = second["turn"]
    assert [item["title"] for item in turn["evidence"]] == ["Bridge closed"]
    # The follow-up cites its own evidence only.
    assert turn["citation_ids"] == ["E1"]
    assert [item["title"] for item in turn["citations"]] == ["Bridge closed"]
    assert re.findall(r"\[(E\d+)\]", turn["answer"]) == ["E1"]
    assert "text" not in turn["evidence"][0]
    # The model saw the first turn as history, without its citation markers.
    [earlier] = generator.requests[1].history
    assert earlier.question == "harbour flood"
    assert earlier.answer == "Harbour flood is relevant."
    assert [item.title for item in generator.requests[1].evidence] == ["Bridge closed"]

    listed = await answering_client.get(f"/research/sessions/{research['id']}/turns")
    assert [item["question"] for item in listed.json()] == ["harbour flood", "bridge closed"]
    fetched = await answering_client.get(f"/research/sessions/{research['id']}")
    assert fetched.json()["id"] == research["id"]


async def test_source_scoped_session_without_a_model(
    client: httpx.AsyncClient, library: dict[str, uuid.UUID]
) -> None:
    research = await create(client, source_id=str(library["paper"]))

    result = await ask(client, research["id"], "harbour flood")

    assert result["turn"]["answer"] is None
    assert result["turn"]["evidence"] == []
    other = await ask(client, research["id"], "bridge closed")
    assert other["turn"]["answer"] is None
    assert [item["source_id"] for item in other["turn"]["evidence"]] == [str(library["paper"])]


async def test_unknown_session_and_source(client: httpx.AsyncClient) -> None:
    missing = uuid.uuid4()

    responses = [
        await client.get(f"/research/sessions/{missing}"),
        await client.get(f"/research/sessions/{missing}/turns"),
        await client.post(f"/research/sessions/{missing}/turns", json={"question": "floods"}),
        await client.post("/research/sessions", json={"source_id": str(missing)}),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]
    assert responses[3].json()["error"]["message"] == "Source was not found."


async def test_export(answering_client: httpx.AsyncClient, library: dict[str, uuid.UUID]) -> None:
    research = await create(answering_client, title="Harbour")
    await ask(answering_client, research["id"], "harbour flood")
    path = f"/research/sessions/{research['id']}/export"

    as_json = await answering_client.get(path)
    as_markdown = await answering_client.get(path, params={"format": "markdown"})

    assert as_json.status_code == 200, as_json.text
    body = as_json.json()
    assert body["session"]["title"] == "Harbour"
    [turn] = body["turns"]
    assert turn["citation_ids"] == ["E1"]
    assert [item["title"] for item in turn["citations"]] == ["Harbour flood"]
    assert [item["evidence_id"] for item in turn["evidence"]] == ["E1"]
    assert as_markdown.status_code == 200
    assert as_markdown.headers["content-type"].startswith("text/markdown")
    assert as_markdown.text.startswith("# Harbour\n")
    assert "- [E1] Harbour flood: " in as_markdown.text


async def test_export_unknown_session(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/research/sessions/{uuid.uuid4()}/export")

    assert response.status_code == 404
