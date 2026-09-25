from collections.abc import Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import httpx

from signalscope.domain.ingestion.errors import IngestionError
from signalscope.ingestion.url_safety import Resolver, check_url, resolve_host

USER_AGENT = "SignalScope"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


class FetchError(IngestionError):
    default_message = "Could not fetch the URL."


@dataclass(frozen=True, slots=True)
class FetchResponse:
    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes

    @property
    def content_type(self) -> str:
        """The media type without parameters, such as "text/html"."""
        return self.headers.get("content-type", "").split(";")[0].strip().lower()


class HttpFetcher:
    """GET requests for ingestion with a timeout, a redirect limit and a size limit.

    Every URL, including each redirect target, must pass check_url before it is
    requested. That is why redirects are followed here instead of by httpx.
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        transport: httpx.AsyncBaseTransport | None = None,
        resolve: Resolver = resolve_host,
    ) -> None:
        self.max_redirects = max_redirects
        self.max_bytes = max_bytes
        self._resolve = resolve
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str) -> FetchResponse:
        for _ in range(self.max_redirects + 1):
            await check_url(url, self._resolve)
            try:
                async with self._client.stream("GET", url) as response:
                    if response.status_code in REDIRECT_STATUS_CODES:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("Redirect response has no Location header.")
                        url = str(response.url.join(location))
                        continue
                    if not response.is_success:
                        raise FetchError(f"Request failed with status {response.status_code}.")
                    body = await self._read_body(response)
                    return FetchResponse(
                        url=str(response.url),
                        status_code=response.status_code,
                        headers={key.lower(): value for key, value in response.headers.items()},
                        body=body,
                    )
            except httpx.TimeoutException as error:
                raise FetchError("Request timed out.") from error
            except httpx.HTTPError as error:
                raise FetchError(f"Request failed ({type(error).__name__}).") from error
        raise FetchError(f"Too many redirects (more than {self.max_redirects}).")

    async def _read_body(self, response: httpx.Response) -> bytes:
        too_large = FetchError(f"Response is larger than {self.max_bytes} bytes.")
        length = response.headers.get("content-length", "")
        if length.isdigit() and int(length) > self.max_bytes:
            raise too_large
        # Read in chunks, so a response without a length cannot fill the memory.
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self.max_bytes:
                raise too_large
            chunks.append(chunk)
        return b"".join(chunks)
