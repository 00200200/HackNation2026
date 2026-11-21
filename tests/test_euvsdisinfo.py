import asyncio
import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastmcp import FastMCP
from mcp.shared.exceptions import MCPError

from prawdowid import euvsdisinfo
from prawdowid.euvsdisinfo import KEY_ENV, LOOKUP_UNAVAILABLE, search_cases

# Shape of the documented `search` result: type, title, content, link.
RESULTS = [
    {
        "type": "claim_review",
        "title": "Poland plans to annex western Ukraine",
        "content": "Recurring pro-Kremlin disinformation narrative about Poland...",
        "link": "https://euvsdisinfo.eu/report/poland-plans-to-annex-western-ukraine/",
    },
    {
        "type": "article",
        "title": "Disinfo Review",
        "content": "x" * 2000,
        "link": "https://euvsdisinfo.eu/disinfo-review/",
    },
    {"type": "claim_review", "title": "No link"},
    {"type": "claim_review", "title": "Broken", "link": "https://[broken"},
    {"type": "claim_review", "title": "Elsewhere", "link": "https://example.com/a"},
    {"type": "unknown", "title": "Other", "link": "https://euvsdisinfo.eu/x/"},
]


def fake_server(search):
    server = FastMCP("fake-euvsdisinfo")
    server.tool(search, name="search")
    return server


def run(server, query="Polska chce zaanektować zachodnią Ukrainę"):
    return asyncio.run(search_cases(query, server=server))


def test_known_case_returns_a_source_with_its_link():
    queries = []

    def search(
        query: str, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        queries.append(query)
        return RESULTS

    lookup = run(fake_server(search))

    assert lookup.limitation is None
    assert queries == ["Polska chce zaanektować zachodnią Ukrainę"]
    case, article = (
        lookup.hits
    )  # no, broken or foreign link and unknown type are dropped
    assert case.kind == "claim_review"
    assert case.source.title == "Poland plans to annex western Ukraine"
    assert str(case.source.url) == RESULTS[0]["link"]
    assert case.source.publisher == "EUvsDisinfo (ESDZ)"
    assert case.source.source_type == "official"
    assert case.source.published_at is None  # `search` gives no date; never guessed
    assert isinstance(case.source.fetched_at, datetime)
    assert article.kind == "article"
    assert len(article.source.fragment) == euvsdisinfo.MAX_FRAGMENT_CHARS


def test_no_key_reports_the_source_unavailable(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)

    lookup = asyncio.run(search_cases("Polska chce zaanektować zachodnią Ukrainę"))

    assert lookup.hits == []
    assert lookup.limitation == LOOKUP_UNAVAILABLE


def test_server_error_is_retried_once_then_a_limitation():
    calls = []

    def search(query: str) -> list[dict]:
        calls.append(query)
        raise RuntimeError("Elasticsearch down")

    lookup = run(fake_server(search))

    assert len(calls) == euvsdisinfo.ATTEMPTS == 2
    assert lookup.hits == []
    assert lookup.limitation == LOOKUP_UNAVAILABLE


def test_retry_recovers_after_one_failure():
    calls = []

    def search(query: str) -> list[dict]:
        calls.append(query)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return RESULTS[:1]

    lookup = run(fake_server(search))

    assert len(lookup.hits) == 1 and lookup.limitation is None


def test_slow_server_hits_the_deadline(monkeypatch):
    monkeypatch.setattr(euvsdisinfo, "DEADLINE_S", 0.2)

    async def search(query: str) -> list[dict]:
        await asyncio.sleep(5)
        return RESULTS

    lookup = run(fake_server(search))

    assert lookup.limitation == LOOKUP_UNAVAILABLE


def test_empty_results_page_is_no_match_not_a_limitation():
    def search(query: str) -> dict:
        return {"results": [], "currentPage": 1, "totalPages": 0, "hasNextPage": False}

    lookup = run(fake_server(search))

    assert lookup.hits == [] and lookup.limitation is None


def test_live_reply_shape_with_paging_and_html_content():
    # Shape the live server returned on 2026-11-21: results wrapped with paging, HTML content.
    def search(query: str) -> dict:
        page = [
            {**RESULTS[0], "content": "<p><em>Poland &amp; Ukraine</em></p> <p>“A”</p>"}
        ]
        return {"results": page, "currentPage": 1, "totalPages": 3, "hasNextPage": True}

    (hit,) = run(fake_server(search)).hits

    assert hit.source.fragment == "Poland & Ukraine “A”"


def test_single_hit_unwrapped_by_the_client_still_counts():
    def search(query: str) -> dict:
        return RESULTS[0]

    assert len(run(fake_server(search)).hits) == 1


@pytest.mark.parametrize("reply", ["not a list", {"error": "boom"}, {"results": "x"}])
def test_unexpected_shape_is_a_limitation(reply):
    def search(query: str) -> str | dict:
        return reply

    assert run(fake_server(search)).limitation == LOOKUP_UNAVAILABLE


@pytest.mark.parametrize("query", ["", "  ab "])
def test_too_short_query_is_not_sent(query):
    def search(query: str) -> list[dict]:
        raise AssertionError("must not be called")

    lookup = run(fake_server(search), query)

    assert lookup.hits == [] and lookup.limitation is None


def test_bad_key_is_not_retried(monkeypatch):
    """Production HTTP branch against a local server that answers like mcp.euvsd.info on a bad key."""
    seen = []

    class Unauthorized(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, self.headers.get("X-API-Key")))
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32001, "message": "Unauthorized"},
                }
            ).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Unauthorized)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    attempts = []
    real_toolset = euvsdisinfo.MCPToolset

    def counting_toolset(*args, **kwargs):
        attempts.append(args)
        return real_toolset(*args, **kwargs)

    monkeypatch.setattr(euvsdisinfo, "URL", f"http://127.0.0.1:{http.server_port}/mcp")
    monkeypatch.setattr(euvsdisinfo, "MCPToolset", counting_toolset)
    monkeypatch.setenv(KEY_ENV, "bad-test-key")
    try:
        lookup = asyncio.run(search_cases("biolab Ukraine"))
    finally:
        http.shutdown()
        http.server_close()

    assert lookup.limitation == LOOKUP_UNAVAILABLE
    assert len(attempts) == 1
    assert seen and all(path == "/mcp" and key == "bad-test-key" for path, key in seen)


def test_sdk_timeout_with_the_same_code_is_still_retried(monkeypatch):
    # The MCP SDK reports its own read timeout with -32001, the server's bad-key code.
    calls = []

    class FlakyToolset:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def direct_call_tool(self, name, args):
            calls.append(name)
            if len(calls) == 1:
                raise MCPError(code=-32001, message="Request 'tools/call' timed out")
            return RESULTS[:1]

    monkeypatch.setattr(euvsdisinfo, "MCPToolset", FlakyToolset)
    monkeypatch.setenv(KEY_ENV, "test-key")

    lookup = asyncio.run(search_cases("biolab Ukraine"))

    assert len(calls) == 2
    assert len(lookup.hits) == 1 and lookup.limitation is None
