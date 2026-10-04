
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_evaluation_routes_are_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    schemas = app.openapi()["components"]["schemas"]

    assert set(paths["/admin/evaluations"]) == {"get"}
    assert set(paths["/admin/evaluations/import"]) == {"post"}
    assert set(paths["/admin/evaluations/{report_id}"]) == {"get"}
    assert {item["name"] for item in paths["/admin/evaluations"]["get"]["parameters"]} == {
        "task",
        "model",
        "provider",
        "dataset_fingerprint",
        "created_from",
        "created_to",
        "limit",
        "offset",
    }
    assert set(schemas["EvaluationReportSummaryRead"]["properties"]) == {
        "id",
        "task",
        "model",
        "provider",
        "dataset_name",
        "dataset_fingerprint",
        "report_version",
        "created_at",
    }


def test_evaluations_need_a_database(client: TestClient) -> None:
    response = client.get("/admin/evaluations")
    assert response.status_code == 503
