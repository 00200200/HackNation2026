"""Link input: fetch a page safely and extract its main text.

The page is untrusted data. It is fetched only over http(s), never from a private, loopback or
link-local address (checked on every connection, so redirects and DNS rebinding are covered),
with at most MAX_REDIRECTS redirects (bodies never read), a DEADLINE_S wall clock and a MAX_BYTES
cap. Only HTML (trafilatura) and PDF (pypdf) are read, in a child process (extract_worker.py)
killed at the deadline, at most MAX_EXTRACTIONS at once; the worker documents its own ceilings. A blocked page, paywall, login wall or social media post
is never worked around: the user is asked to paste the text.
"""

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import socket
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit, urlunsplit

import anyio
import httpcore2
import httpx2
from pydantic import BaseModel

from prawdowid.privacy import mask_personal_data

log = logging.getLogger("prawdowid")
# httpx2 logs every request URL at INFO, before redact() can run; fetch_page logs the redacted one.
logging.getLogger("httpx2").setLevel(logging.WARNING)

MAX_REDIRECTS = 3
DEADLINE_S = 10
MAX_BYTES = 2 * 1024 * 1024
# Below the extracted text, a page shorter than this is a teaser, a cookie wall or a script shell.
MIN_TEXT_CHARS = 200
HTML_TYPES = {"text/html", "application/xhtml+xml"}
PDF_TYPE = "application/pdf"
WORKER = str(Path(__file__).with_name("extract_worker.py"))
# ponytail: one process-wide cap on parser processes; per-worker pools if the API scales out.
MAX_EXTRACTIONS = 2
_extractions = asyncio.Semaphore(MAX_EXTRACTIONS)
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
CREDENTIALS = "Nie pobieramy linków z loginem lub hasłem w adresie. " + PASTE
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

    url: str  # final URL after redirects, redacted; later steps exclude it as evidence for its own claims
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
    # Redirects are followed by hand in fetch_page: httpx2 would read every redirect body whole.
    return httpx2.AsyncClient(
        transport=transport,
        trust_env=False,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
        timeout=DEADLINE_S,
    )


def is_social(url: str) -> bool:
    # "www.facebook.com." is the same host as "www.facebook.com".
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in SOCIAL_HOSTS)


# Query parameters that carry secrets: their values never reach logs, the worker or the answer.
# Matched on the whole decoded name, as is and camelCase split ("accessToken" is "access_Token"), so
# "author" or "zipcode" stay readable for evidence exclusion.
SECRET_PARAM = re.compile(
    r"(.*[_-])?(token|key|apikey|sig|signature|secret|auth|password|passwd|pwd|pass"
    r"|session|session[_-]?id|sid|code|credential|credentials|jwt)",
    re.IGNORECASE,
)


def is_secret(name: str) -> bool:
    name = unquote_plus(name)
    split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return any(SECRET_PARAM.fullmatch(n) for n in (name, split))


def redact(url: str) -> str:
    """The URL for logs, the worker and the answer: no userinfo, no secret values, no fragment."""
    parts = urlsplit(url)
    query = "&".join(
        f"{p.split('=')[0]}=REDACTED" if is_secret(p.split("=")[0]) else p
        for p in parts.query.split("&")
    )
    netloc = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


def check_url(url: str) -> None:
    """Policy for every URL we are about to request: the link itself and each redirect."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise Refusal(BAD_URL)
    if "@" in urlsplit(url).netloc:
        raise Refusal(CREDENTIALS)
    if is_social(url):
        raise Refusal(SOCIAL_MEDIA)
    if LOGIN_PATH.search(urlsplit(url).path):
        raise Refusal(PAYWALL)


async def fetch_page(
    url: str, backend: httpcore2.AsyncNetworkBackend | None = None
) -> Page:
    """Fetch and extract one page, or raise Refusal with the message for the user."""
    check_url(url)
    try:
        async with asyncio.timeout(DEADLINE_S), guarded_client(backend) as client:
            request = client.build_request("GET", url)
            for _ in range(MAX_REDIRECTS + 1):
                check_url(str(request.url))
                resp = await client.send(request, stream=True)
                try:
                    if not resp.has_redirect_location:
                        check_response(resp)
                        body = await read_capped(resp)
                        break
                    if not resp.next_request:  # Location that is not a valid URL
                        raise Refusal(BAD_URL)
                    # A redirect body is never read: closing drops it unread.
                    request = resp.next_request
                finally:
                    await resp.aclose()
            else:
                raise Refusal(TOO_MANY_REDIRECTS)
            page = await extract(body, content_type(resp), redact(str(resp.url)))
    except _PrivateAddress:
        raise Refusal(PRIVATE_ADDRESS) from None
    except httpx2.UnsupportedProtocol:
        raise Refusal(BAD_URL) from None
    except (TimeoutError, httpx2.HTTPError) as exc:
        log.warning(
            "link fetch failed url=%s error=%s",
            mask_personal_data(redact(url)),
            type(exc).__name__,
        )
        raise Refusal(UNREACHABLE, technical=True) from None
    log.info(
        "link fetched url=%s sha256=%s bytes=%d chars=%d",
        mask_personal_data(page.url),
        page.sha256,
        len(body),
        len(page.text),
    )
    return page


def content_type(resp: httpx2.Response) -> str:
    return resp.headers.get("content-type", "").split(";")[0].strip().lower()


def check_response(resp: httpx2.Response) -> None:
    code = resp.status_code
    if code in (401, 402, 403, 407, 429, 451):
        raise Refusal(BLOCKED)
    if code >= 500:
        raise Refusal(UNREACHABLE, technical=True)
    if code >= 400:
        raise Refusal(NOT_FOUND.format(code=code))
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


async def extract(body: bytes, ctype: str, url: str) -> Page:
    """Run the parser on a redacted `url` in a child process, killed if the caller's deadline ends first.

    At most MAX_EXTRACTIONS run at once; a request waits for a slot within its own deadline.
    """
    async with _extractions:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            WORKER,
            ctype,
            url,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await proc.communicate(body)
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
    try:
        result = json.loads(out)
    except ValueError:  # killed by its own limits, or crashed
        log.warning("link extraction failed url=%s returncode=%s", url, proc.returncode)
        raise Refusal(NO_TEXT) from None
    if result["kind"] == "paywall":
        raise Refusal(PAYWALL)
    text = result.get("text") or ""
    if result["kind"] != "ok" or len(text) < MIN_TEXT_CHARS:
        raise Refusal(NO_TEXT)
    return Page(
        url=url,
        sha256=hashlib.sha256(body).hexdigest(),
        title=result["title"],
        publisher=result["publisher"],
        published_at=parse_date(result["date"]),
        text=text,
    )


def parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None
