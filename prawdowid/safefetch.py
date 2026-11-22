"""Safe HTTP GET for URLs we did not choose (search hits now, user links in #4).

- Every hop, redirects included, must pass the caller's `allow(url)` check, use http(s) on the
  default port and be allowed by that host's robots.txt. Redirects are followed by hand, at most
  `MAX_REDIRECTS`, and their bodies are never read.
- The transport resolves each host itself, refuses non-public addresses (loopback, private,
  link-local, reserved, multicast) and connects to the address it checked, so DNS rebinding
  between the check and the connection is not possible.
- Bodies are read up to a byte cap; over it the fetch is refused (`TooLarge`).
- robots.txt (RFC 9309) through Protego, the parser the corpus build uses: it matches `*` and `$`
  (2.2.3), which Python's `RobotFileParser` (3.13) ignores. 200 is parsed (`Disallowed` when it
  says no). Any other 4xx, 401 and 403 included, means the file is unavailable and sets no rules
  (2.3.1.3); `RobotFileParser.read()` would disallow everything on 401/403. 429, 5xx, network
  errors and oversized files mean we do not fetch for now (2.3.1.4, `RobotsUnreachable`) and are
  not cached. Read files are cached for 24 h. A page that itself answers 401 or 403 is still
  never fetched around.
"""

import asyncio
import ipaddress
import logging
import socket
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpcore2
import httpx2
from protego import Protego

log = logging.getLogger("prawdowid")

USER_AGENT = "PrawdowidBot/0.1 (fact-checking demo, HackNation 2026)"
MAX_REDIRECTS = 3
DEFAULT_PORTS = {"http": 80, "https": 443}
DNS_TIMEOUT_S = 5
ROBOTS_MAX_BYTES = 500 * 1024  # the size RFC 9309 asks crawlers to parse
ROBOTS_TTL_S = 24 * 3600  # RFC 9309: do not cache longer than 24 h


class Blocked(Exception):
    """Refused before or while fetching: never sent, or the answer is not usable. No retry."""


class NotAllowed(Blocked):
    """The URL, or a redirect hop, fails the caller's `allow(url)` check."""


class Disallowed(Blocked):
    """robots.txt disallows the URL."""


class RobotsUnreachable(Blocked):
    """robots.txt could not be read (RFC 9309: assume disallow until it can)."""


class TooLarge(Blocked):
    """The body is over the caller's byte cap. `status` is the HTTP status it came with."""

    def __init__(self, message: str, status: int = 200):
        super().__init__(message)
        self.status = status


@dataclass
class Page:
    url: str
    status: int
    content_type: str
    encoding: str | None
    body: bytes

    def text(self) -> str:
        return self.body.decode(self.encoding or "utf-8", errors="replace")


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    return [info[4][0] for info in infos]


class PublicOnlyBackend(httpcore2.AsyncNetworkBackend):
    """Resolves the host, refuses it unless every address is public, connects to that address."""

    def __init__(self, inner: httpcore2.AsyncNetworkBackend | None = None) -> None:
        self._inner = inner or httpcore2.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        try:
            addresses = await asyncio.wait_for(resolve(host, port), DNS_TIMEOUT_S)
        except (OSError, TimeoutError) as exc:
            raise httpcore2.ConnectError(f"cannot resolve {host}: {exc!r}") from exc
        if not addresses or not all(is_public(a) for a in addresses):
            raise httpcore2.ConnectError(f"{host} resolves to a non-public address")
        # TLS still verifies the certificate against `host`: httpcore2 takes the server name
        # from the request URL, not from the address we connect to.
        for address in addresses:  # every one checked; try them in resolver order
            try:
                return await self._inner.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            # Worst case: one connect timeout per address.
            except (httpcore2.ConnectError, httpcore2.ConnectTimeout) as exc:
                error = exc
        raise error

    async def connect_unix_socket(self, *args, **kwargs):
        raise httpcore2.ConnectError("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def public_transport() -> httpx2.AsyncHTTPTransport:
    # trust_env=False: no proxy from the environment, which would connect for us.
    transport = httpx2.AsyncHTTPTransport(trust_env=False)
    # ponytail: httpx2 has no network_backend option, so we replace the pool it built (a private
    # attribute). Recheck on every httpx2 upgrade; test_websearch covers the backend itself.
    transport._pool = httpcore2.AsyncConnectionPool(
        ssl_context=httpx2.create_ssl_context(trust_env=False),
        network_backend=PublicOnlyBackend(),
    )
    return transport


def client(
    timeout: float, transport: httpx2.AsyncBaseTransport | None = None
) -> httpx2.AsyncClient:
    """`transport` is for tests; the default refuses non-public addresses."""
    return httpx2.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        follow_redirects=False,  # get() follows them hop by hop
        transport=transport or public_transport(),
        trust_env=False,
    )


async def get(
    url: str,
    http: httpx2.AsyncClient,
    *,
    allow: Callable[[str], bool],
    max_bytes: int,
    robots: bool = True,
) -> Page:
    """GET `url`. Raises Blocked when refused, httpx2.HTTPError on network errors."""
    for _ in range(MAX_REDIRECTS + 1):
        _check_url(url, allow)
        if robots and not await robots_allow(url, http, allow):
            raise Disallowed(f"{url} disallowed by robots.txt")
        async with http.stream("GET", url) as resp:
            if resp.has_redirect_location:  # a 3xx without Location falls through
                location = resp.headers["location"]
                try:
                    url = urljoin(str(resp.url), location)
                except (
                    ValueError
                ) as exc:  # e.g. "https://[host/x": refuse this hop only
                    raise Blocked(f"malformed redirect {location!r}") from exc
                continue
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > max_bytes:
                    raise TooLarge(f"{url} is over {max_bytes} bytes", resp.status_code)
            return Page(
                url=str(resp.url),
                status=resp.status_code,
                content_type=resp.headers.get("content-type", ""),
                encoding=resp.encoding,
                body=bytes(body),
            )
    raise Blocked(f"more than {MAX_REDIRECTS} redirects")


def _check_url(url: str, allow: Callable[[str], bool]) -> None:
    """The allowlist first: a hop that leaves it is `NotAllowed` whatever its scheme or port."""
    try:
        if not allow(url):
            raise NotAllowed(f"{url} is not allowlisted")
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise Blocked(f"malformed URL {url!r}") from exc
    if parts.scheme not in DEFAULT_PORTS or port not in (
        None,
        DEFAULT_PORTS[parts.scheme],
    ):
        raise Blocked(f"{url}: only http(s) on the default port")


_robots: dict[str, tuple[Protego, float]] = {}


async def robots_allow(
    url: str, http: httpx2.AsyncClient, allow: Callable[[str], bool]
) -> bool:
    """Whether robots.txt lets us fetch `url`. Raises RobotsUnreachable when it cannot be read."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    cached = _robots.get(origin)
    if cached and time.monotonic() - cached[1] < ROBOTS_TTL_S:
        return cached[0].can_fetch(url, USER_AGENT)
    try:
        page = await get(
            f"{origin}/robots.txt",
            http,
            allow=allow,
            max_bytes=ROBOTS_MAX_BYTES,
            robots=False,
        )
    except (Blocked, httpx2.HTTPError, httpx2.InvalidURL) as exc:
        log.warning("robots.txt %s unreadable, not fetching: %r", origin, exc)
        raise RobotsUnreachable(f"robots.txt of {origin} unreadable") from exc
    if page.status == 429 or page.status >= 500:
        log.warning("robots.txt %s: HTTP %d, not fetching", origin, page.status)
        raise RobotsUnreachable(f"robots.txt of {origin}: HTTP {page.status}")
    # Any other answer than 200 (4xx, 401 and 403 too): unavailable, no rules.
    rules = Protego.parse(page.text() if page.status == 200 else "")
    _robots[origin] = (rules, time.monotonic())
    return rules.can_fetch(url, USER_AGENT)
