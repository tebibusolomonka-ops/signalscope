import uuid

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
