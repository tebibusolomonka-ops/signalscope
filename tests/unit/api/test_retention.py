import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

ORGANIZATION = uuid.uuid4()


def test_retention_routes_are_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    schemas = app.openapi()["components"]["schemas"]

    base = "/organizations/{organization_id}/retention"
    assert set(paths[base]) == {"get", "put"}
    assert set(paths[f"{base}/audit-preview"]) == {"get"}
    assert set(paths[f"{base}/audit-cleanup"]) == {"post"}
    assert set(schemas["AuditCleanupRequest"]["properties"]) == {"limit", "confirm"}
    assert set(schemas["AuditRetentionPreviewRead"]["properties"]) == {
        "organization_id",
        "retention_days",
        "cutoff",
        "eligible_count",
    }


def test_retention_needs_authentication(client: TestClient) -> None:
    response = client.get(f"/organizations/{ORGANIZATION}/retention")

    assert response.status_code == 503
