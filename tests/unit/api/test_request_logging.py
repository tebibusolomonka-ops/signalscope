import logging
import re
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REQUEST_LOGGER = "signalscope.api.requests"


@pytest.fixture
def request_logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger=REQUEST_LOGGER)
    return caplog


def request_log_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == REQUEST_LOGGER]


def test_request_is_logged(client: TestClient, request_logs: pytest.LogCaptureFixture) -> None:
    client.get("/health", headers={"X-Request-ID": "log-me"})

    [line] = request_log_lines(request_logs)
    assert re.fullmatch(r"GET /health 200 \d+\.\dms request_id=log-me", line)


def test_query_string_is_not_logged(
    client: TestClient, request_logs: pytest.LogCaptureFixture
) -> None:
    client.get("/health?token=abc123")

    [line] = request_log_lines(request_logs)
    assert line.startswith("GET /health 200 ")
    assert "abc123" not in line


def test_failed_request_is_logged_as_500(
    create_failing_app: Callable[[Exception], FastAPI],
    request_logs: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(create_failing_app(RuntimeError("boom")), raise_server_exceptions=False)

    client.get("/fail")

    [line] = request_log_lines(request_logs)
    assert line.startswith("GET /fail 500 ")
