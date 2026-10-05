from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

JSON_LIMIT = 1024
UPLOAD_LIMIT = 4096


def client() -> TestClient:
    settings = Settings(max_json_request_bytes=JSON_LIMIT, max_upload_request_bytes=UPLOAD_LIMIT)
    return TestClient(create_app(settings))


def test_archive_over_upload_limit_is_rejected() -> None:
    body = b"x" * (UPLOAD_LIMIT * 2)
    response = client().post(
        "/organizations/x/restore?confirm=true",
        content=body,
        headers={"content-type": "application/zip"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_archive_under_upload_limit_passes_the_middleware() -> None:
    body = b"x" * (UPLOAD_LIMIT - 1)
    response = client().post(
        "/organizations/x/restore?confirm=true",
        content=body,
        headers={"content-type": "application/zip"},
    )

    # Not blocked by size; routing/auth handles it (not 413).
    assert response.status_code != 413


def test_upload_limit_is_separate_from_json_limit() -> None:
    # A body between the JSON and upload limits: allowed as an upload, blocked as JSON.
    body = b"x" * (JSON_LIMIT * 2)
    as_zip = client().post(
        "/organizations/x/restore?confirm=true",
        content=body,
        headers={"content-type": "application/zip"},
    )
    as_json = client().post(
        "/organizations/x/restore?confirm=true",
        content=b'{"v":"' + body + b'"}',
        headers={"content-type": "application/json"},
    )

    assert as_zip.status_code != 413
    assert as_json.status_code == 413


@pytest.mark.anyio
async def test_streamed_upload_without_content_length_is_still_limited() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"x" * UPLOAD_LIMIT
        yield b"x"

    app = create_app(
        Settings(max_json_request_bytes=JSON_LIMIT, max_upload_request_bytes=UPLOAD_LIMIT)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        response = await async_client.post(
            "/organizations/x/restore?confirm=true",
            content=chunks(),
            headers={"content-type": "application/zip"},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
