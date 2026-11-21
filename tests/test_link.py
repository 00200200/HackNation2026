"""Link input, offline: fake DNS and a mock network under the real guarded client."""

import asyncio
import ipaddress
import socket

import httpcore2
import pytest
from pydantic_ai import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from prawdowid import link
from prawdowid.contract import Status
from prawdowid.link import (
    BLOCKED,
    MAX_BYTES,
    NO_TEXT,
    PAYWALL,
    PRIVATE_ADDRESS,
    SOCIAL_MEDIA,
    TOO_LARGE,
    TOO_MANY_REDIRECTS,
    UNSUPPORTED_TYPE,
    Refusal,
    fetch_page,
)
from prawdowid.verifier import PAGE_CUT, ExtractedClaim, Extraction, agent, verify

DNS = {
    "news.example": "93.184.216.34",
    "other.example": "93.184.216.35",
    "rebind.example": "10.0.0.7",
    "localhost": "127.0.0.1",
    "twoip.example": ["93.184.216.40", "93.184.216.34"],
}
ARTICLE_TEXT = (
    "Rada Ministrów przyjęła w poniedziałek projekt ustawy o obronie cywilnej. " * 5
)
ARTICLE = f"""<html><head><title>Rząd przyjął projekt</title>
<meta property="og:site_name" content="Gazeta Przykładowa">
<meta property="article:published_time" content="2026-11-16T08:00:00Z"></head>
<body><article><h1>Rząd przyjął projekt</h1><p>{ARTICLE_TEXT}</p></article></body></html>"""


def http(status=200, ctype="text/html; charset=utf-8", body=ARTICLE, headers=()):
    raw = body.encode() if isinstance(body, str) else body
    lines = [
        f"HTTP/1.1 {status} X",
        f"Content-Type: {ctype}",
        f"Content-Length: {len(raw)}",
        "Connection: close",
    ]
    return ("\r\n".join([*lines, *headers, "", ""])).encode() + raw


class FakeNet(httpcore2.AsyncMockBackend):
    """One canned response per IP; records which IPs were really connected to."""

    def __init__(self, responses):
        super().__init__([])
        self.responses = responses
        self.connected = []

    async def connect_tcp(self, host, port, timeout=None, **kwargs):
        self.connected.append(host)
        if host not in self.responses:
            raise httpcore2.ConnectError(f"no route to {host}")
        return httpcore2.AsyncMockStream([self.responses[host]])


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    async def resolve(host, port, **kwargs):
        try:
            ip = DNS[host] if host in DNS else str(ipaddress.ip_address(host))
        except ValueError:
            raise socket.gaierror(f"unknown host {host}") from None
        ips = ip if isinstance(ip, list) else [ip]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (i, port)) for i in ips]

    monkeypatch.setattr(link.anyio, "getaddrinfo", resolve)


def fetch(url, responses):
    net = FakeNet(responses)
    try:
        return asyncio.run(fetch_page(url, backend=net)), net
    except Refusal as refusal:
        return refusal, net


def test_article_is_extracted_with_metadata():
    page, net = fetch("http://news.example/a", {"93.184.216.34": http()})
    assert page.title == "Rząd przyjął projekt"
    assert page.publisher == "Gazeta Przykładowa"
    assert str(page.published_at) == "2026-11-16"
    assert "obronie cywilnej" in page.text
    assert page.url == "http://news.example/a"
    assert len(page.sha256) == 64
    assert net.connected == ["93.184.216.34"]  # the checked IP, not the name


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost:8000/admin",
        "http://10.1.2.3/",
        "http://192.168.0.1/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://rebind.example/",  # public-looking name, private address
    ],
)
def test_private_addresses_are_never_connected(url):
    refusal, net = fetch(url, {})
    assert refusal.message == PRIVATE_ADDRESS and not refusal.technical
    assert net.connected == []


def test_redirect_to_private_address_is_blocked():
    redirect = http(302, body="", headers=["Location: http://169.254.169.254/"])
    refusal, net = fetch("http://news.example/a", {"93.184.216.34": redirect})
    assert refusal.message == PRIVATE_ADDRESS
    assert net.connected == ["93.184.216.34"]


def test_more_than_three_redirects_are_refused():
    loop = http(302, body="", headers=["Location: http://news.example/next"])
    refusal, _ = fetch("http://news.example/a", {"93.184.216.34": loop})
    assert refusal.message == TOO_MANY_REDIRECTS


def test_redirect_is_followed_to_the_final_page():
    redirect = http(301, body="", headers=["Location: http://other.example/final"])
    page, _ = fetch(
        "http://news.example/a",
        {"93.184.216.34": redirect, "93.184.216.35": http()},
    )
    assert page.url == "http://other.example/final"


@pytest.mark.parametrize("status", [401, 403, 429, 451])
def test_blocked_page_asks_to_paste_the_text(status):
    refusal, _ = fetch("http://news.example/a", {"93.184.216.34": http(status)})
    assert refusal.message == BLOCKED


def test_paywall_marked_in_json_ld_is_not_worked_around():
    ld = '<script type="application/ld+json">{"@type": "NewsArticle", "isAccessibleForFree": false}</script>'
    body = ARTICLE.replace("</head>", ld + "</head>")
    refusal, _ = fetch("http://news.example/a", {"93.184.216.34": http(body=body)})
    assert refusal.message == PAYWALL


@pytest.mark.parametrize("path", ["/login?next=/a", "/zaloguj-sie", "/logowanie.html"])
def test_redirect_to_login_is_a_paywall(path):
    redirect = http(302, body="", headers=[f"Location: http://other.example{path}"])
    refusal, _ = fetch(
        "http://news.example/a", {"93.184.216.34": redirect, "93.184.216.35": http()}
    )
    assert refusal.message == PAYWALL


def test_social_media_is_not_fetched():
    refusal, net = fetch("https://www.facebook.com/some/posts/1", {})
    assert refusal.message == SOCIAL_MEDIA
    assert net.connected == []


@pytest.mark.parametrize("ctype", ["image/jpeg", "application/zip", "text/plain"])
def test_non_html_file_is_refused(ctype):
    refusal, _ = fetch(
        "http://news.example/f", {"93.184.216.34": http(ctype=ctype, body=b"\x00" * 10)}
    )
    assert refusal.message == UNSUPPORTED_TYPE


def test_page_over_the_cap_is_refused():
    big = http(body="<html>" + "a" * (MAX_BYTES + 1))
    refusal, _ = fetch("http://news.example/a", {"93.184.216.34": big})
    assert refusal.message == TOO_LARGE


def test_page_without_article_text_is_refused():
    shell = http(
        body="<html><body><div id=app></div><script>x()</script></body></html>"
    )
    refusal, _ = fetch("http://news.example/a", {"93.184.216.34": shell})
    assert refusal.message == NO_TEXT


def test_unreachable_host_is_a_technical_error():
    refusal, _ = fetch("http://nowhere.example/", {})
    assert refusal.technical


def test_link_goes_through_the_same_verify_as_text(monkeypatch):
    net = FakeNet({"93.184.216.34": http()})
    real_fetch = link.fetch_page
    monkeypatch.setattr(
        "prawdowid.verifier.fetch_page", lambda url: real_fetch(url, backend=net)
    )
    seen = []

    def model(messages, info):
        seen.append(messages[-1].parts[-1].content)
        extraction = Extraction(
            claims=[
                ExtractedClaim(
                    claim="Rada Ministrów przyjęła projekt ustawy o obronie cywilnej.",
                    kind="statement",
                    source_sentence="Rada Ministrów przyjęła w poniedziałek projekt.",
                    checkable=True,
                    reason="Fakt.",
                    queries=["projekt ustawy obrona cywilna"],
                )
            ],
            other_claims=[],
            unclear=False,
        )
        return ModelResponse(parts=[TextPart(extraction.model_dump_json())])

    with agent.override(model=FunctionModel(model)):
        result = asyncio.run(verify("http://news.example/a"))

    assert result.status is Status.OK
    assert result.claims[0].claim.startswith("Rada Ministrów")
    assert result.page.url == "http://news.example/a"
    assert result.page.publisher == "Gazeta Przykładowa"
    assert "text" not in result.page.model_dump()  # the page itself is not kept
    # Page text reaches the model wrapped as data, with its publication date.
    assert "<user_text>" in seen[0] and "Data publikacji: 2026-11-16" in seen[0]
    assert PAGE_CUT not in result.claims[0].limitations  # short page, nothing cut


def test_refused_link_is_a_notice_not_a_verdict():
    def never(messages, info):
        raise AssertionError("model must not be called for a refused link")

    with agent.override(model=FunctionModel(never)):
        result = asyncio.run(verify("http://127.0.0.1:8000/"))
    assert result.status is Status.CANNOT_CHECK
    assert result.message == PRIVATE_ADDRESS
    assert result.claims == []


@pytest.mark.parametrize(
    "ip, public",
    [
        ("93.184.216.34", True),
        ("2606:2800:220:1::1", True),
        ("64:ff9b::a00:1", False),  # NAT64 form of 10.0.0.1
        ("2002:a00:1::", False),  # 6to4 form of 10.0.0.1
        ("fe80::1%en0", False),
        ("100.64.0.1", False),  # carrier-grade NAT
        ("::7f00:1", False),  # IPv4-compatible form of 127.0.0.1
    ],
)
def test_ipv6_forms_of_private_addresses_are_not_public(ip, public):
    assert link.is_public(ip) is public


def test_guard_is_installed_in_the_client_pool():
    # httpx2 has no public hook for the network backend; fail loudly if the private one moves.
    client = link.guarded_client()
    assert isinstance(client._transport._pool._network_backend, link.GuardedBackend)


def test_article_about_logging_in_is_not_a_paywall():
    page, _ = fetch(
        "http://news.example/web/logowanie-do-epuap-jak-to-zrobic",
        {"93.184.216.34": http()},
    )
    assert page.title == "Rząd przyjął projekt"


def test_long_page_is_cut_and_says_so(monkeypatch):
    long_page = link.Page(
        url="http://news.example/a",
        sha256="0" * 64,
        title=None,
        publisher=None,
        published_at=None,
        text="Sejm uchwalił ustawę. " * 400,
    )

    async def fake_fetch(url):
        return long_page

    monkeypatch.setattr("prawdowid.verifier.fetch_page", fake_fetch)
    seen = []

    def model(messages, info):
        seen.append(messages[-1].parts[-1].content)
        claim = ExtractedClaim(
            claim="Sejm uchwalił ustawę.",
            kind="statement",
            source_sentence="Sejm uchwalił ustawę.",
            checkable=True,
            reason="Fakt.",
            queries=[],
        )
        extraction = Extraction(claims=[claim], other_claims=[], unclear=False)
        return ModelResponse(parts=[TextPart(extraction.model_dump_json())])

    with agent.override(model=FunctionModel(model)):
        result = asyncio.run(verify("http://news.example/a"))
    assert PAGE_CUT in result.claims[0].limitations
    assert len(seen[0]) < len(long_page.text)


def test_next_checked_address_is_tried_when_the_first_fails():
    page, net = fetch("http://twoip.example/a", {"93.184.216.34": http()})
    assert page.title == "Rząd przyjął projekt"
    assert net.connected == ["93.184.216.40", "93.184.216.34"]


def test_malformed_pdf_is_no_text():
    broken = http(ctype="application/pdf", body=b"%PDF-1.7\n garbage")
    refusal, _ = fetch("http://news.example/f.pdf", {"93.184.216.34": broken})
    assert refusal.message == NO_TEXT
