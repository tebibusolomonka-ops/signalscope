from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.api.security_policy import (
    DEVELOPMENT_CSP,
    PRODUCTION_CSP,
    content_security_policy,
)
from signalscope.core.settings import Environment, Settings


def test_production_policy_is_restrictive() -> None:
    assert content_security_policy(Settings(environment=Environment.PRODUCTION)) == PRODUCTION_CSP
    assert "default-src 'self'" in PRODUCTION_CSP
    assert "frame-ancestors 'none'" in PRODUCTION_CSP
    assert "object-src 'none'" in PRODUCTION_CSP
    # Scripts are limited to this origin with no eval and no inline.
    assert "script-src 'self';" in PRODUCTION_CSP
    assert "unsafe-eval" not in PRODUCTION_CSP
    assert "'unsafe-inline'" not in PRODUCTION_CSP.split("style-src")[0]


def test_production_policy_allows_same_origin_api_only() -> None:
    assert "connect-src 'self'" in PRODUCTION_CSP
    # No third-party origins and no wildcard source.
    assert "http://" not in PRODUCTION_CSP
    assert "https://" not in PRODUCTION_CSP
    assert "*" not in PRODUCTION_CSP


def test_development_policy_differs_and_allows_dev_tooling() -> None:
    assert content_security_policy(Settings(environment=Environment.DEVELOPMENT)) == DEVELOPMENT_CSP
    assert content_security_policy(Settings(environment=Environment.TEST)) == DEVELOPMENT_CSP
    assert "unsafe-eval" in DEVELOPMENT_CSP
    assert "ws:" in DEVELOPMENT_CSP
    assert DEVELOPMENT_CSP != PRODUCTION_CSP


def test_production_app_sends_production_policy() -> None:
    client = TestClient(create_app(Settings(environment=Environment.PRODUCTION)))

    response = client.get("/health")

    assert response.headers["Content-Security-Policy"] == PRODUCTION_CSP


def test_development_app_sends_development_policy() -> None:
    client = TestClient(create_app(Settings(environment=Environment.DEVELOPMENT)))

    response = client.get("/health")

    assert response.headers["Content-Security-Policy"] == DEVELOPMENT_CSP
