import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from signalscope.domain.ingestion.errors import IngestionError

type Resolver = Callable[[str], Awaitable[list[str]]]
type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class UnsafeUrlError(IngestionError):
    default_message = "URL is not allowed."


async def resolve_host(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        results = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise IngestionError(f"Could not resolve host {host}.") from error
    return [str(result[4][0]) for result in results]


async def check_url(url: str, resolve: Resolver = resolve_host) -> None:
    """Raise UnsafeUrlError unless the URL is http or https on a public address.

    Hostnames are resolved and every address must be public. httpx resolves the
    host again when it connects, so a DNS answer that changes in between is not
    caught here.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeUrlError("Only http and https URLs can be fetched.")
    if parts.username is not None or parts.password is not None:
        raise UnsafeUrlError("URLs with a user name or password are not allowed.")
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise UnsafeUrlError("URL has no host.")
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeUrlError(f"URL points to a local address: {host}.")

    try:
        addresses: list[IPAddress] = [ipaddress.ip_address(host)]
    except ValueError:
        addresses = [ipaddress.ip_address(address) for address in await resolve(host)]
    if not addresses:
        raise IngestionError(f"Could not resolve host {host}.")
    for address in addresses:
        if not _is_public(address):
            raise UnsafeUrlError(f"URL points to a private or reserved address: {host}.")


def _is_public(address: IPAddress) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
