"""Link input: fetch a page safely and extract its main text.

The page is untrusted data. It is fetched only over http(s), never from a private, loopback or
link-local address (checked on every connection, so redirects and DNS rebinding are covered),
with at most MAX_REDIRECTS redirects, a DEADLINE_S wall clock and a MAX_BYTES cap. Only HTML
(trafilatura) and PDF (pypdf) are read. A blocked page, paywall, login wall or social media post
is never worked around: the user is asked to paste the text.
"""

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import socket
from datetime import date
from io import BytesIO
from urllib.parse import urlsplit

import anyio
import httpcore2
import httpx2
import trafilatura
from pydantic import BaseModel
from pypdf import PdfReader

log = logging.getLogger("prawdowid")

MAX_REDIRECTS = 3
DEADLINE_S = 10
MAX_BYTES = 2 * 1024 * 1024
# Below the extracted text, a page shorter than this is a teaser, a cookie wall or a script shell.
MIN_TEXT_CHARS = 200
HTML_TYPES = {"text/html", "application/xhtml+xml"}
PDF_TYPE = "application/pdf"
USER_AGENT = "Prawdowid/0.1 (fact-checking; fetches one page on a user's request)"
# ponytail: a fixed list of hosts that need a login or app to show a post; extend as needed.
SOCIAL_HOSTS = {
    "facebook.com",
    "fb.com",
    "fb.watch",
    "instagram.com",
    "threads.net",
    "threads.com",
    "x.com",
    "twitter.com",
    "t.co",
    "tiktok.com",
    "linkedin.com",
    "youtube.com",
    "youtu.be",
    "t.me",
    "telegram.me",
    "vk.com",
    "wykop.pl",
}
LOGIN_PATH = re.compile(
    r"/(login|signin|sign-in|logowanie|zaloguj(-sie)?)(\.\w+)?(/|$)", re.IGNORECASE
)

PASTE = "Skopiuj tekst ze strony i wklej go tutaj, a sprawdzimy go."
SOCIAL_MEDIA = (
    "Nie pobieramy wpisów z mediów społecznościowych, bo zwykle wymagają logowania. "
    + PASTE
)
BLOCKED = "Ta strona nie pozwala na automatyczne pobranie treści. " + PASTE
PAYWALL = (
    "Ta strona jest za paywallem lub wymaga logowania. "
    "Nie obchodzimy takich zabezpieczeń. " + PASTE
)
NO_TEXT = "Nie udało się wyodrębnić tekstu artykułu z tej strony. " + PASTE
UNSUPPORTED_TYPE = (
    "Pod tym linkiem nie ma strony HTML ani pliku PDF, więc nie możemy go sprawdzić. "
    + PASTE
)
TOO_LARGE = "Ta strona jest za duża, by ją pobrać (limit 2 MB). " + PASTE
PRIVATE_ADDRESS = "Ten adres prowadzi do sieci prywatnej lub lokalnej. Sprawdzamy tylko publiczne strony."
BAD_URL = "Przyjmujemy tylko adresy zaczynające się od http:// lub https://."
NOT_FOUND = (
    "Pod tym linkiem nie ma strony (błąd {code}). Sprawdź adres albo wklej tekst."
)
TOO_MANY_REDIRECTS = f"Ten link przekierowuje więcej niż {MAX_REDIRECTS} razy. " + PASTE
UNREACHABLE = (
    f"Nie udało się pobrać tej strony w ciągu {DEADLINE_S} s. Spróbuj ponownie za chwilę "
    "albo wklej tekst."
)


class Page(BaseModel):
    """What later steps need from the page: never the page itself."""

    url: str  # final URL after redirects; later steps exclude it as evidence for its own claims
    sha256: str  # of the fetched bytes
    title: str | None
    publisher: str | None
    published_at: date | None
    text: str


class Refusal(Exception):
    """The page cannot be checked. `technical` marks an outage, not a property of the page."""

    def __init__(self, message: str, technical: bool = False):
        super().__init__(message)
        self.message = message
        self.technical = technical


class _PrivateAddress(httpx2.ConnectError):
    pass


class GuardedBackend(httpcore2.AnyIOBackend):
    """Resolves the host itself and connects only to the public address it checked."""

    def __init__(self, inner: httpcore2.AsyncNetworkBackend | None = None):
        self._inner = inner or httpcore2.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, **kwargs):
        try:
            infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise httpcore2.ConnectError(f"cannot resolve {host}: {exc}") from exc
        ips = list(dict.fromkeys(info[4][0] for info in infos))
        if not ips or not all(is_public(ip) for ip in ips):
            raise _PrivateAddress(f"blocked address for {host}")
        # Every address is checked; try them in turn, as a plain connect would.
        for ip in ips[:-1]:
            try:
                return await self._inner.connect_tcp(
                    ip, port, timeout=timeout, **kwargs
                )
            except (httpcore2.ConnectError, httpcore2.ConnectTimeout):
                continue
        return await self._inner.connect_tcp(ips[-1], port, timeout=timeout, **kwargs)


NAT64 = ipaddress.ip_network("64:ff9b::/96")


def is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address):
        # IPv6 forms that carry an IPv4 address: check the IPv4 address they lead to.
        if addr.ipv4_mapped or addr.sixtofour:
            addr = addr.ipv4_mapped or addr.sixtofour
        elif addr in NAT64:
            addr = ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return addr.is_global and not (addr.is_multicast or addr.is_reserved)


def guarded_client(
    backend: httpcore2.AsyncNetworkBackend | None = None,
) -> httpx2.AsyncClient:
    transport = httpx2.AsyncHTTPTransport(trust_env=False)
    # The transport has no public hook for the network backend; the pool does.
    transport._pool = httpcore2.AsyncConnectionPool(
        network_backend=GuardedBackend(backend), max_connections=4
    )
    return httpx2.AsyncClient(
        transport=transport,
        trust_env=False,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        headers={"User-Agent": USER_AGENT},
        timeout=DEADLINE_S,
    )


def is_social(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in SOCIAL_HOSTS)


async def fetch_page(
    url: str, backend: httpcore2.AsyncNetworkBackend | None = None
) -> Page:
    """Fetch and extract one page, or raise Refusal with the message for the user."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise Refusal(BAD_URL)
    if is_social(url):
        raise Refusal(SOCIAL_MEDIA)
    try:
        async with (
            asyncio.timeout(DEADLINE_S),
            guarded_client(backend) as client,
            client.stream("GET", url) as resp,
        ):
            final_url = str(resp.url)
            if is_social(final_url):
                raise Refusal(SOCIAL_MEDIA)
            check_response(resp, final_url)
            body = await read_capped(resp)
            # Off the event loop, inside the fetch deadline.
            # ponytail: a timed-out extraction thread still runs to the end; a process pool if abused.
            page = await asyncio.to_thread(extract, body, content_type(resp), final_url)
    except _PrivateAddress:
        raise Refusal(PRIVATE_ADDRESS) from None
    except httpx2.TooManyRedirects:
        raise Refusal(TOO_MANY_REDIRECTS) from None
    except httpx2.UnsupportedProtocol:  # a redirect to ftp:, file: and the like
        raise Refusal(BAD_URL) from None
    except (TimeoutError, httpx2.HTTPError) as exc:
        log.warning("link fetch failed url=%s error=%r", url, exc)
        raise Refusal(UNREACHABLE, technical=True) from None
    log.info(
        "link fetched url=%s sha256=%s bytes=%d chars=%d",
        page.url,
        page.sha256,
        len(body),
        len(page.text),
    )
    return page


def content_type(resp: httpx2.Response) -> str:
    return resp.headers.get("content-type", "").split(";")[0].strip().lower()


def check_response(resp: httpx2.Response, final_url: str) -> None:
    code = resp.status_code
    if code in (401, 402, 403, 407, 429, 451):
        raise Refusal(BLOCKED)
    if code >= 500:
        raise Refusal(UNREACHABLE, technical=True)
    if code >= 400:
        raise Refusal(NOT_FOUND.format(code=code))
    if LOGIN_PATH.search(urlsplit(final_url).path):
        raise Refusal(PAYWALL)
    if content_type(resp) not in HTML_TYPES | {PDF_TYPE}:
        raise Refusal(UNSUPPORTED_TYPE)
    if int(resp.headers.get("content-length") or 0) > MAX_BYTES:
        raise Refusal(TOO_LARGE)


async def read_capped(resp: httpx2.Response) -> bytes:
    body = bytearray()
    async for chunk in resp.aiter_bytes():
        body += chunk
        if len(body) > MAX_BYTES:
            raise Refusal(TOO_LARGE)
    return bytes(body)


def extract(body: bytes, ctype: str, url: str) -> Page:
    sha256 = hashlib.sha256(body).hexdigest()
    if ctype == PDF_TYPE:
        try:
            reader = PdfReader(BytesIO(body))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
            title = reader.metadata.title if reader.metadata else None
        # pypdf raises many types on a malformed file; any of them means no text.
        except Exception:  # noqa: BLE001
            raise Refusal(NO_TEXT) from None
        publisher, published = None, None
    else:
        if is_paywalled(body):
            raise Refusal(PAYWALL)
        doc = trafilatura.bare_extraction(
            body, url=url, with_metadata=True, include_comments=False
        )
        text = doc.text if doc else ""
        title = doc.title if doc else None
        publisher = doc.sitename if doc else None
        published = parse_date(doc.date if doc else None)
    text = (text or "").strip()
    if len(text) < MIN_TEXT_CHARS:
        raise Refusal(NO_TEXT)
    return Page(
        url=url,
        sha256=sha256,
        title=str(title) if title else None,
        publisher=publisher,
        published_at=published,
        text=text,
    )


def is_paywalled(html: bytes) -> bool:
    """schema.org marks paywalled articles with isAccessibleForFree: false in JSON-LD."""
    for raw in re.findall(
        rb"<script[^>]+application/ld\+json[^>]*>(.*?)</script>",
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if str(item.get("isAccessibleForFree", "")).lower() == "false":
                    return True
                stack.extend(item.values())
    return False


def parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None
