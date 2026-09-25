import httpx
import pytest

from signalscope.domain.ingestion.errors import FetchError, IngestionError
from signalscope.domain.ingestion.registry import UnsupportedSourceTypeError
from signalscope.domain.ingestion.retry import RetryPolicy, is_retryable
from signalscope.ingestion.http import HttpFetcher
from signalscope.ingestion.url_safety import UnsafeUrlError


def test_default_policy() -> None:
    policy = RetryPolicy()

    assert (policy.max_attempts, policy.base_delay_seconds, policy.max_delay_seconds) == (
        3,
        5.0,
        300.0,
    )


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"max_attempts": 0}, "max_attempts must be at least 1"),
        ({"base_delay_seconds": -1}, "base_delay_seconds must not be negative"),
        ({"base_delay_seconds": 10, "max_delay_seconds": 5}, "must not be smaller"),
    ],
)
def test_invalid_policy_is_rejected(values: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        RetryPolicy(**values)  # type: ignore[arg-type]


def test_delay_doubles_after_each_attempt() -> None:
    policy = RetryPolicy(max_attempts=6, base_delay_seconds=2, max_delay_seconds=100)

    assert [policy.delay_after(attempt) for attempt in range(1, 6)] == [2, 4, 8, 16, 32]


def test_delay_stops_at_the_maximum() -> None:
    policy = RetryPolicy(max_attempts=100, base_delay_seconds=5, max_delay_seconds=60)

    assert [policy.delay_after(attempt) for attempt in [4, 5, 6]] == [40, 60, 60]
    assert policy.delay_after(10_000) == 60


def test_attempt_numbers_start_at_one() -> None:
    with pytest.raises(ValueError, match="start at 1"):
        RetryPolicy().delay_after(0)


def test_retries_stop_at_the_last_attempt() -> None:
    policy = RetryPolicy(max_attempts=3)

    assert [policy.allows_retry_after(attempt) for attempt in [1, 2, 3]] == [True, True, False]


@pytest.mark.parametrize("status_code", [429, 502, 503, 504])
def test_temporary_http_statuses_are_retryable(status_code: int) -> None:
    assert is_retryable(FetchError("Server busy.", status_code=status_code))


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 410, 500])
def test_other_http_statuses_are_not_retryable(status_code: int) -> None:
    assert not is_retryable(FetchError("No.", status_code=status_code))


@pytest.mark.parametrize(
    "error",
    [
        UnsafeUrlError("URL points to a private or reserved address: internal."),
        UnsupportedSourceTypeError("No ingestion adapter is available for api sources."),
        IngestionError("Response is not an RSS or Atom feed."),
        FetchError("Response is larger than 10 bytes."),
        ValueError("url must not be empty"),
        RuntimeError("something unexpected"),
    ],
)
def test_other_failures_are_not_retryable(error: Exception) -> None:
    assert not is_retryable(error)


async def public_address(host: str) -> list[str]:
    return ["93.184.215.14"]


async def fetch_error(handler: httpx.MockTransport) -> FetchError:
    async with HttpFetcher(transport=handler, resolve=public_address) as fetcher:
        with pytest.raises(FetchError) as error:
            await fetcher.get("https://news.example/feed")
    return error.value


@pytest.mark.anyio
@pytest.mark.parametrize(
    "exception", [httpx.ReadTimeout("slow"), httpx.ConnectError("refused"), httpx.ReadError("cut")]
)
async def test_network_failures_from_the_fetcher_are_retryable(exception: Exception) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    error = await fetch_error(httpx.MockTransport(handler))

    assert error.network_error
    assert is_retryable(error)


@pytest.mark.anyio
async def test_fetcher_keeps_the_status_code() -> None:
    error = await fetch_error(httpx.MockTransport(lambda request: httpx.Response(503)))

    assert error.status_code == 503
    assert not error.network_error
    assert is_retryable(error)
