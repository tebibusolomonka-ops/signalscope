from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from signalscope.ingestion.http import FetchError, HttpFetcher

pytestmark = pytest.mark.anyio

Handler = Callable[[httpx.Request], httpx.Response]


def fetcher(handler: Handler, **options: int) -> HttpFetcher:
    return HttpFetcher(transport=httpx.MockTransport(handler), **options)


async def test_successful_fetch() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            content=b"<html>Hello</html>",
            headers={"Content-Type": "text/html; charset=utf-8", "X-Extra": "yes"},
        )

    async with fetcher(handler) as client:
        response = await client.get("https://example.com/page")

    assert response.url == "https://example.com/page"
    assert response.status_code == 200
    assert response.body == b"<html>Hello</html>"
    assert response.content_type == "text/html"
    assert response.headers["x-extra"] == "yes"
    assert seen[0].headers["user-agent"] == "SignalScope"


async def test_redirects_are_followed_to_the_final_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "/new"})
        return httpx.Response(200, content=b"moved here")

    async with fetcher(handler) as client:
        response = await client.get("https://example.com/old")

    assert response.url == "https://example.com/new"
    assert response.body == b"moved here"


async def test_redirect_loop_stops() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "/again"})

    async with fetcher(handler, max_redirects=3) as client:
        with pytest.raises(FetchError, match="Too many redirects"):
            await client.get("https://example.com/start")


async def test_redirect_without_location_is_an_error() -> None:
    async with fetcher(lambda request: httpx.Response(302)) as client:
        with pytest.raises(FetchError, match="no Location header"):
            await client.get("https://example.com/")


@pytest.mark.parametrize("status_code", [404, 500, 304])
async def test_non_success_status_is_an_error(status_code: int) -> None:
    async with fetcher(lambda request: httpx.Response(status_code)) as client:
        with pytest.raises(FetchError, match=f"status {status_code}"):
            await client.get("https://example.com/")


async def test_timeout_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    async with fetcher(handler) as client:
        with pytest.raises(FetchError, match="Request timed out."):
            await client.get("https://example.com/")


async def test_connection_problem_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with fetcher(handler) as client:
        with pytest.raises(FetchError, match=r"Request failed \(ConnectError\)."):
            await client.get("https://example.com/")


async def test_body_at_the_limit_is_allowed() -> None:
    async with fetcher(
        lambda request: httpx.Response(200, content=b"x" * 10), max_bytes=10
    ) as client:
        response = await client.get("https://example.com/")

    assert len(response.body) == 10


async def test_body_over_the_limit_is_rejected() -> None:
    async with fetcher(
        lambda request: httpx.Response(200, content=b"x" * 11), max_bytes=10
    ) as client:
        with pytest.raises(FetchError, match="larger than 10 bytes"):
            await client.get("https://example.com/")


async def test_body_without_length_is_still_limited() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(5):
            yield b"x" * 4

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=chunks())

    async with fetcher(handler, max_bytes=10) as client:
        with pytest.raises(FetchError, match="larger than 10 bytes"):
            await client.get("https://example.com/")
