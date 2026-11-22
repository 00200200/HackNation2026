"""Per-query cache in front of Tavily (#110, #75): reruns and repeated questions spend no Tavily
credits. Only the Tavily path uses it; Perplexity calls (`websearch.default_search`) are not cached.

`cached_tavily_search` has the `SearchProvider` signature and wraps `websearch.tavily_search`.
Key: sha256 of the casefolded, whitespace-folded query + sorted domains + limit (the query is
already PII-masked by `search_web`; only the hash is stored, never the query). Value: what Tavily
returned for it, as `SearchHit` fields (url, title, snippet, published date).

- TTL `PRAWDOWID_SEARCH_CACHE_TTL_S` (default 86400, never above `RETENTION_DAYS`; 0 turns the cache off).
- In memory: `cachetools.TTLCache`, at most `MAX_ENTRIES`. Persisted in `search_cache.jsonl` next to
  the source cache (`PRAWDOWID_SEARCH_CACHE_PATH` overrides) so a container restart keeps it.
- Failures and limit answers are never cached. A limit answer starts a short cool-down in which
  no call is made at all, so the retry in `search_web` does not wait for a second refusal.
- Counters: `STATS` (process) and `track()` (one check) say how many calls reached Tavily and how
  many answers came from the cache.

websearch imports this module for its default provider, so it must not import websearch at load.
"""

import contextlib
import contextvars
import hashlib
import json
import logging
import os
import threading
import time
from collections import Counter
from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path

from cachetools import TTLCache

from prawdowid.cache import CACHE_PATH
from prawdowid.privacy import RETENTION_DAYS

log = logging.getLogger("prawdowid")

DEFAULT_TTL_S = 86_400
MAX_ENTRIES = 2_000
LIMIT_COOLDOWN_S = 60
SWEEP_INTERVAL_S = 3600  # how often expired rows leave the file without a new write
# `SearchUnavailable` message of a Tavily usage or plan limit; `is_limit` tells it from other failures.
LIMIT_REASON = "search limit exceeded"

STATS: Counter[str] = Counter()  # tavily_calls, cache_hits, limit_errors, failures
_check: contextvars.ContextVar[Counter[str] | None] = contextvars.ContextVar(
    "search_cache_check", default=None
)


@contextlib.contextmanager
def track() -> Iterator[Counter[str]]:
    """Counts of the lookups made inside the block (worker threads started from it included)."""
    counts: Counter[str] = Counter()
    token = _check.set(counts)
    try:
        yield counts
    finally:
        _check.reset(token)


def _count(name: str) -> None:
    STATS[name] += 1
    counts = _check.get()
    if counts is not None:
        counts[name] += 1


def ttl_s() -> float:
    try:
        ttl = float(os.getenv("PRAWDOWID_SEARCH_CACHE_TTL_S") or DEFAULT_TTL_S)
    except ValueError:
        ttl = DEFAULT_TTL_S
    return max(0.0, min(ttl, RETENTION_DAYS * 86_400))


def make_key(query: str, domains: Sequence[str], limit: int) -> str:
    folded = " ".join(query.casefold().split())
    raw = json.dumps([folded, sorted(d.casefold() for d in domains), limit])
    return hashlib.sha256(raw.encode()).hexdigest()


class SearchCache:
    """Thread-safe TTL cache of search hits (each a dict of SearchHit fields), optionally on disk."""

    def __init__(
        self,
        ttl: float,
        path: Path | None = None,
        maxsize: int = MAX_ENTRIES,
        clock=time.time,
    ) -> None:
        self.ttl, self.path, self.maxsize, self.clock = ttl, path, maxsize, clock
        self._items: TTLCache[str, tuple[float, list[dict]]] = TTLCache(
            maxsize=maxsize, ttl=ttl, timer=clock
        )
        self._lock = threading.Lock()
        self._lines = 0
        self._swept = clock()
        if path:
            self._load()

    def get(self, key: str) -> list[dict] | None:
        with self._lock:
            self._sweep()
            entry = self._items.get(key)
        if entry and self.clock() - entry[0] < self.ttl:
            return entry[1]
        return None

    def _sweep(self) -> None:
        """Drops expired rows from the file at most hourly, with or without new writes (caller
        holds the lock). Kept rows keep their original timestamps."""
        now = self.clock()
        if not self.path or now - self._swept < min(self.ttl, SWEEP_INTERVAL_S):
            return
        self._swept = now
        for key in [
            k for k, (stored, _) in self._items.items() if now - stored >= self.ttl
        ]:
            del self._items[key]
        if self._lines != len(self._items):
            with contextlib.suppress(OSError):
                self._rewrite()

    def put(self, key: str, hits: list[dict]) -> None:
        now = self.clock()
        with self._lock:
            self._items[key] = (now, hits)
            if not self.path:
                return
            self._lines += 1
            try:
                if self._lines > 2 * self.maxsize:
                    self._rewrite()
                else:
                    self._append(key, now, hits)
            except (
                OSError
            ) as exc:  # a read-only disk costs the restart survival, not the check
                log.warning("search cache not saved: %s", type(exc).__name__)

    def _load(self) -> None:
        from prawdowid.websearch import SearchHit  # websearch imports this module

        try:
            raw_lines = self.path.read_bytes().splitlines()
        except OSError:
            return
        now = self.clock()
        lines = []
        for raw in raw_lines:
            # A write cut off inside a multi-byte character leaves an undecodable line: skip it.
            try:
                lines.append(raw.decode("utf-8"))
            except UnicodeDecodeError:
                continue
        damaged = len(raw_lines) - len(lines)
        for line in lines:
            # Any line that is not a full, valid record is skipped: a damaged file never takes web
            # search down (pydantic's ValidationError is a ValueError).
            try:
                row = json.loads(line)
                key, stored = row["key"], float(row["stored_at"])
                if not isinstance(row["hits"], list):
                    continue
                hits = [
                    SearchHit.model_validate(h).model_dump(mode="json")
                    for h in row["hits"]
                ]
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if now - stored < self.ttl:
                self._items[key] = (stored, hits)
        self._lines = len(self._items)
        if (
            len(lines) + damaged != self._lines
        ):  # expired and damaged lines leave the file now
            with contextlib.suppress(OSError):
                self._rewrite()

    def _append(self, key: str, stored_at: float, hits: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(_row(key, stored_at, hits))

    def _rewrite(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(_row(k, s, h) for k, (s, h) in self._items.items())
        tmp.replace(self.path)
        self._lines = len(self._items)


def _row(key: str, stored_at: float, hits: list[dict]) -> str:
    return (
        json.dumps(
            {"key": key, "stored_at": stored_at, "hits": hits}, ensure_ascii=False
        )
        + "\n"
    )


_cache: SearchCache | None = None
_cache_ttl = -1.0
_limit_until = 0.0
_init_lock = threading.Lock()


def _store() -> SearchCache | None:
    """The process cache, built on first use and again when the TTL setting changes; None when off."""
    global _cache, _cache_ttl
    ttl = ttl_s()
    with _init_lock:
        if ttl != _cache_ttl:
            path = Path(
                os.getenv("PRAWDOWID_SEARCH_CACHE_PATH")
                or CACHE_PATH.with_name("search_cache.jsonl")
            )
            _cache = SearchCache(ttl, path) if ttl > 0 else None
            _cache_ttl = ttl
        return _cache


def is_limit(exc: BaseException) -> bool:
    """True for the `SearchUnavailable` this module raises on a Tavily usage or plan limit."""
    return str(exc).startswith(LIMIT_REASON)


def _limit_cause(exc: BaseException) -> str | None:
    """Tavily's own limit text, from the SDK error behind a `SearchUnavailable`, else None.
    The SDK maps HTTP 429 to UsageLimitExceededError and 403/432/433 to ForbiddenError, whose
    text names the exceeded plan or pay-as-you-go limit."""
    from tavily import UsageLimitExceededError
    from tavily.errors import ForbiddenError

    cause = exc.__cause__
    if isinstance(cause, UsageLimitExceededError):
        return str(cause) or "usage limit"
    if isinstance(cause, ForbiddenError) and any(
        word in str(cause).lower() for word in ("limit", "exceeds")
    ):
        return str(cause)
    return None


def cached_tavily_search(query: str, *, domains: Sequence[str], limit: int):
    """`SearchProvider`: the cached answer when there is one, else one Tavily call, cached."""
    global _limit_until
    from prawdowid import websearch

    store = _store()
    key = make_key(query, domains, limit)
    if store and (cached := store.get(key)) is not None:
        _count("cache_hits")
        log.info("tavily search: cache hit")
        try:
            return [websearch.SearchHit(**h) for h in cached]
        except (ValueError, TypeError):  # a bad entry is a miss, never an error
            log.warning("tavily search: unreadable cache entry, calling the provider")
    if time.monotonic() < _limit_until:
        raise websearch.SearchUnavailable(f"{LIMIT_REASON} (cool-down, no call made)")
    _count("tavily_calls")
    try:
        hits = websearch.tavily_search(query, domains=domains, limit=limit)
    except websearch.SearchUnavailable as exc:
        if reason := _limit_cause(exc):
            _count("limit_errors")
            _limit_until = time.monotonic() + LIMIT_COOLDOWN_S
            log.warning("tavily search: limit reached: %s", reason)
            raise websearch.SearchUnavailable(f"{LIMIT_REASON}: {reason}") from exc
        _count("failures")
        raise
    log.info("tavily search: call, %d hits", len(hits))
    if store:
        store.put(key, [_dump(h) for h in hits])
    return hits


def _dump(hit) -> dict:
    return {
        "url": hit.url,
        "title": hit.title,
        "snippet": hit.snippet,
        "published_date": hit.published_date.isoformat()
        if isinstance(hit.published_date, date)
        else None,
    }
