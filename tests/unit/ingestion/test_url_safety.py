import httpx
import pytest

from signalscope.domain.ingestion.errors import IngestionError
from signalscope.ingestion.http import HttpFetcher
from signalscope.ingestion.url_safety import UnsafeUrlError, check_url

pytestmark = pytest.mark.anyio

# Fake DNS, so the tests never depend on real name lookups.
DNS = {
    "news.example": ["93.184.215.14"],
    "dual.example": ["93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c"],
    "internal.example": ["10.0.0.5"],
    "sneaky.example": ["93.184.215.14", "127.0.0.1"],
    "empty.example": [],
}


async def fake_resolve(host: str) -> list[str]:
    if host not in DNS:
        raise IngestionError(f"Could not resolve host {host}.")
    return DNS[host]


@pytest.mark.parametrize(
    "url",
    [
        "https://news.example/feed.xml",
        "http://news.example/",
        "https://news.example:8443/page",
        "https://dual.example/",
        "https://93.184.215.14/",
    ],
)
async def test_public_urls_are_allowed(url: str) -> None:
    await check_url(url, fake_resolve)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://LOCALHOST./",
        "http://api.localhost/",
        "http://127.0.0.1/",
        "http://127.8.9.10:8000/",
        "http://[::1]/",
        "http://10.1.2.3/",
        "http://172.16.0.1/",
        "http://172.31.255.255/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[fe80::1]/",
        "http://0.0.0.0/",
        "http://[::]/",
        "http://224.0.0.1/",
        "http://240.0.0.1/",
        "http://100.64.0.1/",
        "http://[::ffff:127.0.0.1]/",
        "http://internal.example/",
        "http://sneaky.example/",
    ],
)
async def test_local_and_private_urls_are_blocked(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        await check_url(url, fake_resolve)


@pytest.mark.parametrize(
    "url",
    ["http://user:pass@news.example/", "http://user@news.example/", "http://:x@news.example/"],
)
async def test_urls_with_credentials_are_blocked(url: str) -> None:
    with pytest.raises(UnsafeUrlError, match="user name or password"):
        await check_url(url, fake_resolve)


@pytest.mark.parametrize(
    "url",
    ["ftp://news.example/file", "file:///etc/passwd", "gopher://news.example/", "news.example"],
)
async def test_other_schemes_are_blocked(url: str) -> None:
    with pytest.raises(UnsafeUrlError, match="Only http and https"):
        await check_url(url, fake_resolve)


async def test_url_without_host_is_blocked() -> None:
    with pytest.raises(UnsafeUrlError, match="no host"):
        await check_url("http:///path", fake_resolve)


@pytest.mark.parametrize("url", ["https://unknown.example/", "https://empty.example/"])
async def test_host_that_does_not_resolve_is_an_error(url: str) -> None:
    with pytest.raises(IngestionError, match="Could not resolve host"):
        await check_url(url, fake_resolve)


async def test_fetcher_checks_redirect_targets() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://internal.example/admin"})

    fetcher = HttpFetcher(transport=httpx.MockTransport(handler), resolve=fake_resolve)
    async with fetcher:
        with pytest.raises(UnsafeUrlError, match="private or reserved"):
            await fetcher.get("https://news.example/start")

    assert requested == ["https://news.example/start"]


async def test_fetcher_does_not_request_an_unsafe_url() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200)

    fetcher = HttpFetcher(transport=httpx.MockTransport(handler), resolve=fake_resolve)
    async with fetcher:
        with pytest.raises(UnsafeUrlError):
            await fetcher.get("http://127.0.0.1:8000/")

    assert requested == []
