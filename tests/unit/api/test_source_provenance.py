import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_route_is_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    schema = app.openapi()["components"]["schemas"]["SourceProvenanceRead"]

    assert set(paths["/sources/{source_id}/provenance"]) == {"get"}
    assert set(schema["properties"]) == {
        "source_id",
        "document_count",
        "first_document_at",
        "last_document_at",
        "first_published_at",
        "last_published_at",
        "entity_count",
        "claim_count",
        "event_count",
        "event_cluster_count",
        "cross_source_event_cluster_count",
        "revision_count",
    }


def test_no_judgement_fields(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]
    words = ("credib", "trust", "reliab", "score", "rank")

    for name in schemas:
        assert not any(word in name.lower() for word in ("credib", "trust", "reliab"))
    properties = schemas["SourceProvenanceRead"]["properties"]
    assert not any(word in field for field in properties for word in words)


def test_bad_source_id() -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.get("/sources/not-a-uuid/provenance")

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["path", "source_id"]


def test_needs_a_database(client: TestClient) -> None:
    assert client.get(f"/sources/{uuid.uuid4()}/provenance").status_code == 503


def test_compare_route_is_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    schemas = app.openapi()["components"]["schemas"]

    assert set(paths["/sources/compare"]) == {"post"}
    assert set(schemas["SourceComparisonRead"]["properties"]) == {
        "sources",
        "shared_event_cluster_count",
        "shared_entity_count",
        "shared_claim_count",
    }
    assert set(schemas["ComparedSourceRead"]["properties"]) == {"source", "provenance"}
    words = ("better", "worse", "trust", "reliab", "score", "rank", "winner", "best")
    for name in ("SourceComparisonRead", "ComparedSourceRead", "SourceComparisonRequest"):
        fields = " ".join(schemas[name]["properties"]).lower()
        assert not any(word in fields for word in words), name


@pytest.mark.parametrize(
    "source_ids",
    [
        [],
        [str(uuid.uuid4())],
        [str(uuid.uuid4()) for _ in range(11)],
        ["not-a-uuid", str(uuid.uuid4())],
    ],
    ids=["none", "too few", "too many", "bad id"],
)
def test_compare_bad_request(source_ids: list[str]) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.post("/sources/compare", json={"source_ids": source_ids})

    assert response.status_code == 422


def test_compare_duplicates_are_rejected() -> None:
    same = str(uuid.uuid4())
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.post("/sources/compare", json={"source_ids": [same, same]})

    assert response.status_code == 422
    assert "only be compared once" in response.text
