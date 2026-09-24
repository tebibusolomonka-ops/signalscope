import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.pagination import Page, Pagination


@pytest.fixture
def paged_client(app: FastAPI) -> TestClient:
    @app.get("/numbers")
    async def numbers(page: Pagination) -> Page[int]:
        items = list(range(250))
        return Page(
            items=items[page.offset : page.offset + page.limit],
            total=len(items),
            limit=page.limit,
            offset=page.offset,
        )

    return TestClient(app)


def test_default_page(paged_client: TestClient) -> None:
    body = paged_client.get("/numbers").json()

    assert body["items"] == list(range(50))
    assert (body["total"], body["limit"], body["offset"]) == (250, 50, 0)


def test_custom_limit_and_offset(paged_client: TestClient) -> None:
    body = paged_client.get("/numbers", params={"limit": 3, "offset": 10}).json()

    assert body == {"items": [10, 11, 12], "total": 250, "limit": 3, "offset": 10}


def test_maximum_limit_is_allowed(paged_client: TestClient) -> None:
    body = paged_client.get("/numbers", params={"limit": 100}).json()

    assert len(body["items"]) == 100


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": -1}, {"limit": 101}, {"offset": -1}, {"limit": "many"}],
)
def test_invalid_page_params_are_rejected(
    paged_client: TestClient, params: dict[str, object]
) -> None:
    response = paged_client.get("/numbers", params=params)

    assert response.status_code == 422


def test_page_model_validates_items() -> None:
    page = Page[int](items=[1, 2], total=5, limit=2, offset=0)

    assert page.model_dump() == {"items": [1, 2], "total": 5, "limit": 2, "offset": 0}
    with pytest.raises(ValueError):
        Page[int](items=["not a number"], total=1, limit=1, offset=0)  # type: ignore[list-item]
