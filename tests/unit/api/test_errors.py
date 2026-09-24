import uuid
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from signalscope.core.errors import ConflictError, NotFoundError


class Item(BaseModel):
    name: str = Field(max_length=5)
    count: int


def test_not_found_error_returns_404(
    create_failing_app: Callable[[Exception], FastAPI],
) -> None:
    client = TestClient(create_failing_app(NotFoundError("Source was not found.")))

    response = client.get("/fail")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Source was not found."},
    }


def test_conflict_error_returns_409(create_failing_app: Callable[[Exception], FastAPI]) -> None:
    client = TestClient(create_failing_app(ConflictError()))

    response = client.get("/fail")

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "conflict", "message": "Resource conflicts with existing data."},
    }


def test_unexpected_error_is_not_handled(
    create_failing_app: Callable[[Exception], FastAPI],
) -> None:
    client = TestClient(create_failing_app(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        client.get("/fail")


def test_unexpected_error_response_hides_details(
    create_failing_app: Callable[[Exception], FastAPI],
) -> None:
    app = create_failing_app(RuntimeError("secret detail"))
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/fail")

    assert response.status_code == 500
    assert "secret detail" not in response.text
    assert "Traceback" not in response.text


def test_invalid_path_value_uses_error_format(app: FastAPI) -> None:
    @app.get("/items/{item_id}")
    async def read_item(item_id: uuid.UUID) -> str:
        return str(item_id)

    response = TestClient(app).get("/items/not-a-uuid")

    error = response.json()["error"]
    assert response.status_code == 422
    assert error["code"] == "validation_error"
    assert error["message"] == "Request validation failed."
    [detail] = error["details"]
    assert detail["loc"] == ["path", "item_id"]
    assert detail["type"] == "uuid_parsing"
    assert detail["message"]


def test_invalid_body_lists_each_field_without_echoing_input(app: FastAPI) -> None:
    @app.post("/items")
    async def create_item(item: Item) -> Item:
        return item

    response = TestClient(app).post("/items", json={"name": "secret-value", "count": "many"})

    error = response.json()["error"]
    assert response.status_code == 422
    assert error["code"] == "validation_error"
    assert [detail["loc"] for detail in error["details"]] == [["body", "name"], ["body", "count"]]
    assert all(set(detail) == {"loc", "message", "type"} for detail in error["details"])
    assert "secret-value" not in response.text


def test_unknown_route_uses_error_format(client: TestClient) -> None:
    response = client.get("/no-such-page")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}


def test_wrong_method_uses_error_format(client: TestClient) -> None:
    response = client.post("/health")

    assert response.status_code == 405
    assert response.json() == {
        "error": {"code": "method_not_allowed", "message": "Method Not Allowed"},
    }
    assert response.headers["allow"] == "GET"
