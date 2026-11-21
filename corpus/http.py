"""Polite HTTP client for the collectors.

Rules from the brief (section 5) and the team: respect robots.txt (RFC 9309, longest match, via
Protego), about one request per second per registered domain, a generic User-Agent, bounded
timeouts and retries. A bot challenge, 401, 403 or 429 is never worked around: the caller stops
the source. Responses are cached on disk; `max_age` decides when a cached answer is too old.
"""

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx2
from protego import Protego

from corpus.schema import registered_domain

USER_AGENT = "faktczyfejk-corpus/0.1 (research prototype; respects robots.txt)"
MAX_REDIRECTS = 5
REDIRECTS = (301, 302, 303, 307, 308)
REFUSALS = (401, 403, 429)
# Markers of a bot challenge page (Incapsula, Cloudflare, Akamai). Only trusted on short bodies.
CHALLENGE_MARKERS = (
    "_Incapsula_Resource",
    "Just a moment...",
    "Access Denied",
    "cf-chl",
)


class FetchError(Exception):
    """The page could not be fetched; the message is the reason shown in the build report."""


class Disallowed(FetchError):
    """robots.txt disallows this path. Other paths of the site may still be fetched."""


class Blocked(FetchError):
    """The site refuses automated clients, or its robots.txt cannot be read. Stop the source."""


@dataclass(frozen=True)
class Page:
    url: str
    text: str
    content_type: str
    fetched_at: str  # UTC ISO timestamp of the real network fetch


def is_challenge(response: httpx2.Response) -> bool:
    """A bot challenge instead of content: an empty "202 Accepted" (AWS WAF, used by EUR-Lex)
    or a short page with a known challenge script."""
    if response.status_code == 202 and not response.content.strip():
        return True
    text = response.text
    return len(text) < 3000 and any(marker in text for marker in CHALLENGE_MARKERS)


class PoliteClient:
    def __init__(
        self,
        cache_dir: Path | None = None,
        *,
        refresh: bool = False,
        interval: float = 1.0,
        timeout: float = 20.0,
        retries: int = 2,
        backoff: float = 1.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._client = httpx2.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "pl,en;q=0.5"},
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
        )
        self._cache_dir = cache_dir
        self._refresh = refresh
        self._interval = interval
        self._retries = retries
        self._backoff = backoff
        self._robots: dict[str, Protego] = {}
        self._robots_blocked: dict[
            str, str
        ] = {}  # origin -> why it must not be crawled
        self._next_slot: dict[str, float] = {}
        self._lock = threading.Lock()

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        check_robots: bool = True,
        max_age: float | None = None,
    ) -> Page:
        """GET one page, honouring robots.txt and the per-domain rate limit.

        A cached copy is used unless it is older than `max_age` seconds (None: never too old).
        `headers` carries API keys, so they never end up in a URL or in the cache; they are
        dropped when a redirect leaves the origin. `check_robots=False` is only for documented
        API endpoints used under their own terms.
        """
        if (cached := self._cache_read(url, max_age)) is not None:
            return cached
        page = self._fetch(url, headers=headers, check_robots=check_robots)
        self._cache_write(url, page)
        return page

    def get_json(self, url: str, *, max_age: float | None = None):
        return json.loads(self.get(url, max_age=max_age).text)

    # -- fetching ---------------------------------------------------------------------------

    def _fetch(
        self, url: str, *, headers: dict[str, str] | None, check_robots: bool
    ) -> Page:
        origin = self._origin(url)
        for _ in range(MAX_REDIRECTS + 1):
            if check_robots:
                self._check_robots(url)
            response = self._request(
                url, headers if self._origin(url) == origin else None
            )
            if response.status_code in REDIRECTS:
                url = urljoin(url, response.headers.get("location", ""))
                continue
            return self._to_page(url, response)
        raise FetchError("too many redirects")

    def _to_page(self, url: str, response: httpx2.Response) -> Page:
        if response.status_code in REFUSALS:
            raise Blocked(
                f"HTTP {response.status_code}: site refuses automated clients"
            )
        if is_challenge(response):
            raise Blocked(f"bot challenge (HTTP {response.status_code}), not bypassed")
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code}")
        if not response.text.strip():
            raise FetchError(f"empty response (HTTP {response.status_code})")
        return Page(
            url=url,
            text=response.text,
            content_type=response.headers.get("content-type", ""),
            fetched_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )

    def _request(
        self, url: str, headers: dict[str, str] | None = None
    ) -> httpx2.Response:
        """One GET with retries on network errors and 5xx. Redirects are left to the caller."""
        reason = ""
        for attempt in range(self._retries + 1):
            if attempt:
                time.sleep(self._backoff * 2**attempt)
            self._throttle(url)
            try:
                response = self._client.get(url, headers=headers)
            except httpx2.HTTPError as exc:
                reason = f"{type(exc).__name__}: {exc}"
                continue
            if response.status_code < 500:
                return response
            reason = f"HTTP {response.status_code}"
        raise FetchError(reason)

    def _throttle(self, url: str) -> None:
        """Reserve the next free slot for this registered domain, then wait for it."""
        key = registered_domain(url) or urlsplit(url).netloc
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot.get(key, 0.0))
            self._next_slot[key] = slot + self._delay_for(url)
        if slot > now:
            time.sleep(slot - now)

    def _delay_for(self, url: str) -> float:
        rules = self._robots.get(self._origin(url))
        delay = rules.crawl_delay(USER_AGENT) if rules else None
        return max(self._interval, delay or 0.0)

    # -- robots.txt -------------------------------------------------------------------------

    @staticmethod
    def _origin(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    def _check_robots(self, url: str) -> None:
        origin = self._origin(url)
        with self._lock:
            rules, blocked = self._robots.get(origin), self._robots_blocked.get(origin)
        if blocked:
            raise Blocked(blocked)
        if rules is None:
            try:
                rules = self._load_robots(origin)
            except Blocked as exc:
                with self._lock:
                    self._robots_blocked[origin] = str(
                        exc
                    )  # do not ask again in this build
                raise
            with self._lock:
                self._robots[origin] = rules
        if not rules.can_fetch(url, USER_AGENT):
            raise Disallowed("robots.txt disallows this path")

    def _load_robots(self, origin: str) -> Protego:
        """RFC 9309: follow redirects; 4xx means no rules; 5xx, no answer, 429 or a bot
        challenge means do not crawl."""
        url = f"{origin}/robots.txt"
        try:
            for _ in range(MAX_REDIRECTS + 1):
                response = self._request(url)
                if response.status_code not in REDIRECTS:
                    break
                url = urljoin(url, response.headers.get("location", ""))
            else:
                raise FetchError("too many redirects")
        except FetchError as exc:
            raise Blocked(f"robots.txt unavailable ({exc})") from exc
        if response.status_code == 429 or is_challenge(response):
            raise Blocked(
                f"robots.txt answered with a refusal (HTTP {response.status_code})"
            )
        if response.status_code == 200:
            return Protego.parse(response.text)
        return Protego.parse("")

    # -- disk cache -------------------------------------------------------------------------

    def _cache_path(self, url: str) -> Path | None:
        if self._cache_dir is None:
            return None
        return self._cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.json"

    def _cache_read(self, url: str, max_age: float | None) -> Page | None:
        path = self._cache_path(url)
        if self._refresh or path is None or not path.exists():
            return None
        try:
            page = Page(**json.loads(path.read_text(encoding="utf-8")))
            age = datetime.now(UTC) - datetime.fromisoformat(page.fetched_at)
        except (
            ValueError,
            TypeError,
        ):  # cut JSON, bad UTF-8 or a bad date: a miss, not an error
            return None
        if max_age is not None and age.total_seconds() > max_age:
            return None
        return page

    def _cache_write(self, url: str, page: Page) -> None:
        path = self._cache_path(url)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(page.__dict__, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)  # atomic: an interrupted build never leaves half a file
