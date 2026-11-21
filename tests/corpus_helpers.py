"""Offline helpers for the corpus tests: saved pages and a client whose network is a dict."""

from datetime import date
from pathlib import Path

import httpx2

from corpus.catalog import Source
from corpus.http import PoliteClient

FIXTURES = Path(__file__).parent / "fixtures" / "corpus"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def offline_client(routes: dict, calls: list | None = None, **options) -> PoliteClient:
    """`routes` maps a URL to a body or to (status, body). Anything else answers 404, so a
    site without a routed robots.txt has no crawl rules. Requests are appended to `calls`."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if calls is not None:
            calls.append(request)
        answer = routes.get(str(request.url), (404, "not found"))
        status, body = answer if isinstance(answer, tuple) else (200, answer)
        if 300 <= status < 400:
            return httpx2.Response(status, headers={"location": body})
        return httpx2.Response(status, text=body, headers={"content-type": "text/html"})

    options = {"interval": 0, "backoff": 0, **options}
    return PoliteClient(transport=httpx2.MockTransport(handler), **options)


def source(**overrides) -> Source:
    fields = {
        "id": "test-source",
        "domain": "example.gov.pl",
        "publisher": "Urząd Testowy",
        "source_type": "official",
        "licence": "CC BY-SA 4.0",
        "storage": "full_text",
        "access": "test",
        "update_interval": "24h",
        "added": date(2026, 11, 21),
        "status": "active",
        "collector": "news_list",
    }
    return Source(**{**fields, **overrides})
