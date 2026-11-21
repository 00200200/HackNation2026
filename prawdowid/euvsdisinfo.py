"""Known-narrative lookup in EUvsDisinfo (EEAS East StratCom) through its MCP server.

The server's `search` tool does full-text search over EUvsDisinfo disinformation cases
(`claim_review`) and analytical articles. Each hit comes back as a `Source` candidate for reranking:
a match says the claim resembles a documented pro-Kremlin narrative, which is context, never a
verdict on its own. A missing key, bad key or outage is a limitation.

Docs: EUvsDisinfo MCP docs, Fibery, 2025/2026 (Streamable HTTP, JSON-RPC 2.0, API key header).
"""

import asyncio
import html
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError
from pydantic_ai.mcp import MCPToolset

from prawdowid.contract import Source
from prawdowid.websearch import ALLOWLIST

log = logging.getLogger("prawdowid")

URL = "https://mcp.euvsd.info/mcp"
KEY_ENV = "EUVSDISINFO_API_KEY"
TIMEOUT_S = 8  # connect/initialize and each read
DEADLINE_S = 15  # whole lookup, retry included
ATTEMPTS = 2  # first call plus one retry; a slow first attempt uses up the deadline
MAX_HITS = 5
MAX_QUERY_CHARS = 200
MAX_FRAGMENT_CHARS = 800
MAX_TITLE_CHARS = 300
MIN_QUERY_CHARS = 3  # the server rejects shorter queries
AUTH_ERROR_CODE = -32001  # JSON-RPC code of HTTP 401, missing or invalid key
_DOMAIN = ALLOWLIST["euvsdisinfo.eu"]

LOOKUP_UNAVAILABLE = (
    "Wyszukiwanie w bazie EUvsDisinfo było niedostępne, "
    "więc nie sprawdziliśmy, czy to twierdzenie powtarza znany przypadek dezinformacji."
)


class EuvsdisinfoHit(BaseModel):
    source: Source
    # "claim_review": a documented disinformation case; "article": an analytical article.
    kind: Literal["claim_review", "article"]


class EuvsdisinfoLookup(BaseModel):
    hits: list[EuvsdisinfoHit] = []
    # Set when the lookup could not run; goes to ClaimResult.limitations.
    limitation: str | None = None


async def search_cases(query: str, *, server: Any = None) -> EuvsdisinfoLookup:
    """Search EUvsDisinfo for the claim or one of its search queries.

    `server` replaces the remote server (tests pass an in-process FastMCP server).
    """
    query = query.strip()[:MAX_QUERY_CHARS]
    if len(query) < MIN_QUERY_CHARS:
        return EuvsdisinfoLookup()
    key = os.getenv(KEY_ENV)
    if server is None and not key:
        log.warning("euvsdisinfo lookup skipped: %s is not set", KEY_ENV)
        return EuvsdisinfoLookup(limitation=LOOKUP_UNAVAILABLE)

    try:
        async with asyncio.timeout(DEADLINE_S):
            items = await _search(query, server, key)
    except TimeoutError:
        log.warning("euvsdisinfo unavailable: no answer within %s s", DEADLINE_S)
        return EuvsdisinfoLookup(limitation=LOOKUP_UNAVAILABLE)
    if items is None:
        return EuvsdisinfoLookup(limitation=LOOKUP_UNAVAILABLE)
    if (
        isinstance(items, dict) and "results" in items
    ):  # live server: one page plus paging
        items = items["results"]
    if isinstance(items, dict) and "type" in items:  # one hit comes back unwrapped
        items = [items]
    if not isinstance(items, list):
        log.warning("euvsdisinfo unavailable: search result is not a list")
        return EuvsdisinfoLookup(limitation=LOOKUP_UNAVAILABLE)

    fetched_at = datetime.now(UTC)
    hits = [hit for item in items if (hit := _to_hit(item, fetched_at))]
    return EuvsdisinfoLookup(hits=hits[:MAX_HITS])


async def _search(query: str, server: Any, key: str | None) -> Any:
    """`search` tool call with one retry. None when every attempt failed."""
    for attempt in range(1, ATTEMPTS + 1):
        # Header, not ?key=, so the key never shows up in logged URLs.
        toolset = (
            MCPToolset(server, tool_error_behavior="error")
            if server is not None
            else MCPToolset(
                URL,
                headers={"X-API-Key": key},
                init_timeout=TIMEOUT_S,
                read_timeout=TIMEOUT_S,
                tool_error_behavior="error",
            )
        )
        try:
            async with toolset:
                return await toolset.direct_call_tool("search", {"query": query})
        except Exception as exc:  # noqa: BLE001 - any transport, auth or tool error is a limitation
            # Type only: the message of an HTTP error can carry the request URL and headers.
            log.warning(
                "euvsdisinfo attempt %d failed: %s", attempt, type(exc).__name__
            )
            if _is_bad_key(exc):
                break  # a bad key stays bad: no retry
    return None


def _is_bad_key(exc: Exception) -> bool:
    # -32001 is the server's "missing or invalid API key" and also the MCP SDK's own
    # request timeout ("Request 'tools/call' timed out"), which is worth a retry.
    message = str(getattr(exc, "message", ""))
    return getattr(exc, "code", None) == AUTH_ERROR_CODE and "timed out" not in message


def _to_hit(item: Any, fetched_at: datetime) -> EuvsdisinfoHit | None:
    if not isinstance(item, dict) or item.get("type") not in (
        "claim_review",
        "article",
    ):
        return None
    # Only EUvsDisinfo's own pages carry its source type; a link elsewhere is not its case.
    try:
        host = urlsplit(str(item.get("link") or "")).hostname or ""
    except ValueError:  # e.g. "https://[broken"
        log.warning("euvsdisinfo hit skipped: malformed link")
        return None
    if host != "euvsdisinfo.eu" and not host.endswith(".euvsdisinfo.eu"):
        log.warning("euvsdisinfo hit skipped: link is not on euvsdisinfo.eu")
        return None
    content = item.get("content")
    try:
        source = Source(
            title=(item.get("title") or item["link"])[:MAX_TITLE_CHARS],
            publisher=_DOMAIN.publisher,
            # `search` returns no date. Unknown, never guessed.
            published_at=None,
            fetched_at=fetched_at,
            url=item["link"],
            source_type=_DOMAIN.source_type,
            # Retrieved text is untrusted data: shown and quoted, never followed.
            fragment=_text(content)[:MAX_FRAGMENT_CHARS] or None
            if isinstance(content, str)
            else None,
        )
    except (KeyError, TypeError, ValidationError):
        log.warning("euvsdisinfo hit skipped: no usable link")
        return None
    return EuvsdisinfoHit(source=source, kind=item["type"])


def _text(content: str) -> str:
    """`content` is HTML (`<p>`, `<a>`, entities); the fragment is plain text."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", content)).split())
