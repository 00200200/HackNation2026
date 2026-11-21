"""Link input, offline: fake DNS and a mock network under the real guarded client."""

import asyncio
import io
import ipaddress
import os
import socket
import subprocess
import time

import httpcore2
import pytest
from pydantic_ai import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from prawdowid import extract_worker, link
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
from prawdowid.verifier import (
    MAX_PAGE_CHARS,
    PAGE_CUT,
    ExtractedClaim,
    Extraction,
    agent,
    page_text,
    verify,
)

DNS = {
    "news.example": "93.184.216.34",
    "other.example": "93.184.216.35",
    "rebind.example": "10.0.0.7",
    "localhost": "127.0.0.1",
    "twoip.example": ["93.184.216.40", "93.184.216.34"],
    "www.facebook.com": "93.184.216.50",
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
        self.read_bytes = 0

    async def connect_tcp(self, host, port, timeout=None, **kwargs):
        self.connected.append(host)
        if host not in self.responses:
            raise httpcore2.ConnectError(f"no route to {host}")
        chunks = self.responses[host]
        return CountingStream(chunks if isinstance(chunks, list) else [chunks], self)


class CountingStream(httpcore2.AsyncMockStream):
    """Counts the bytes the client really pulled from the network."""

    def __init__(self, chunks, net):
        super().__init__(chunks)
        self.net = net

    async def read(self, max_bytes, timeout=None):
        data = await super().read(max_bytes, timeout)
        self.net.read_bytes += len(data)
        return data


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


@pytest.mark.usefixtures("quiet_sources")
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


@pytest.mark.usefixtures("quiet_sources")
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


def test_injection_on_a_page_is_logged_as_from_the_page(monkeypatch):
    net = FakeNet({"93.184.216.34": http()})
    real_fetch = link.fetch_page
    monkeypatch.setattr(
        "prawdowid.verifier.fetch_page", lambda url: real_fetch(url, backend=net)
    )
    claim = ExtractedClaim(
        claim="Rada Ministrów przyjęła projekt ustawy.",
        kind="statement",
        source_sentence="Rada Ministrów przyjęła projekt.",
        checkable=True,
        reason="Fakt.",
        queries=[],
    )
    extraction = Extraction(
        claims=[claim], other_claims=[], unclear=False, injection_found=True
    )
    model = FunctionModel(
        lambda messages, info: ModelResponse(
            parts=[TextPart(extraction.model_dump_json())]
        )
    )
    with agent.override(model=model):
        result = asyncio.run(verify("http://news.example/a"))
    assert [e.location for e in result.security_events] == ["page"]


def test_refused_link_costs_nothing():
    result = asyncio.run(verify("http://10.0.0.1/"))
    assert result.cost_usd == 0.0


def test_redirect_body_is_never_read():
    # 20 MB in 1 MB chunks behind a redirect; only the headers may be read.
    head = http(302, body="", headers=["Location: http://other.example/final"])
    head = head.replace(b"Content-Length: 0", f"Content-Length: {20 * 2**20}".encode())
    redirect = [head] + [b"x" * 2**20] * 20
    page, net = fetch(
        "http://news.example/a",
        {"93.184.216.34": redirect, "93.184.216.35": http()},
    )
    assert page.url == "http://other.example/final"
    assert net.read_bytes < 2 * len(http())


def test_invalid_redirect_location_is_refused():
    bad = http(302, body=ARTICLE, headers=["Location: http://a:abc/"])
    refusal, _ = fetch("http://news.example/a", {"93.184.216.34": bad})
    assert refusal.message == link.BAD_URL


def test_dotted_social_host_is_not_fetched():
    refusal, net = fetch("http://www.facebook.com./posts/a", {})
    assert refusal.message == SOCIAL_MEDIA
    assert net.connected == []


def test_redirect_to_social_host_opens_no_connection_to_it():
    redirect = http(302, body="", headers=["Location: https://www.facebook.com/p/1"])
    refusal, net = fetch(
        "http://news.example/a",
        {"93.184.216.34": redirect, "93.184.216.50": http()},
    )
    assert refusal.message == SOCIAL_MEDIA
    assert net.connected == ["93.184.216.34"]


SLOW_WORKER = """
import os, sys, time
open(os.path.join(sys.argv[0] + ".pids"), "a").write(f"{os.getpid()}\\n")
time.sleep(60)
"""


@pytest.fixture
def slow_worker(tmp_path, monkeypatch):
    worker = tmp_path / "worker.py"
    worker.write_text(SLOW_WORKER)
    monkeypatch.setattr(link, "WORKER", str(worker))
    monkeypatch.setattr(link, "DEADLINE_S", 3)
    return tmp_path / "worker.py.pids"


def pids(path):
    return [int(p) for p in path.read_text().split()] if path.exists() else []


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); ps shows it as Z.
    state = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], check=False, capture_output=True
    )
    return bool(state.stdout.strip()) and not state.stdout.startswith(b"Z")


def test_extraction_past_the_deadline_is_killed(slow_worker):
    started = time.monotonic()
    refusal, _ = fetch("http://news.example/a", {"93.184.216.34": http()})
    assert refusal.technical and refusal.message == link.UNREACHABLE
    assert time.monotonic() - started < 8
    [pid] = pids(slow_worker)
    assert not alive(pid)


def test_parallel_extractions_are_capped(slow_worker, monkeypatch):
    # Count live parsers in-process at each spawn: a waiter whose deadline ends just after a slot
    # frees may still start a worker, so the total started is timing-dependent; the peak is not.
    procs, peak = [], []
    spawn = asyncio.create_subprocess_exec

    async def counted(*args, **kwargs):
        procs.append(await spawn(*args, **kwargs))
        # Counted once this one runs: the first two both sleep 60 s, so the second sees two.
        peak.append(sum(p.returncode is None for p in procs))
        return procs[-1]

    monkeypatch.setattr(link.asyncio, "create_subprocess_exec", counted)

    async def go():
        monkeypatch.setattr(link, "_extractions", asyncio.Semaphore(2))
        net = FakeNet({"93.184.216.34": http()})
        return await asyncio.gather(
            *[fetch_page("http://news.example/a", backend=net) for _ in range(4)],
            return_exceptions=True,
        )

    results = asyncio.run(go())
    assert all(isinstance(r, Refusal) and r.technical for r in results)
    assert max(peak) == 2  # two ran at once, never three
    assert all(p.returncode is not None for p in procs)  # every parser was reaped
    assert not any(alive(p.pid) for p in procs)


def test_pdf_extraction_stops_at_its_page_and_text_budget():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 10 10 Td (" + b"Ala ma kota " * 100 + b") Tj ET")
    content_ref = writer._add_object(content)
    for _ in range(300):  # every page draws the same content stream
        page = writer.add_blank_page(612, 792)
        page[NameObject("/Contents")] = content_ref
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
    buf = io.BytesIO()
    writer.write(buf)

    result = extract_worker.extract_pdf(buf.getvalue())
    assert result["kind"] == "ok"
    one_page = 1200
    assert len(result["text"]) <= extract_worker.MAX_TEXT_CHARS
    assert len(result["text"]) >= extract_worker.MAX_TEXT_CHARS - one_page


def test_long_title_and_publisher_share_the_page_budget():
    page = link.Page(
        url="http://news.example/a",
        sha256="0" * 64,
        title="T" * 10_000,
        publisher="P" * 10_000,
        published_at=None,
        text="Krótki artykuł. " * 30,
    )
    text, cut = page_text(page)
    assert len(text) <= MAX_PAGE_CHARS
    assert "T" * 201 not in text and "P" * 201 not in text
    assert not cut  # all of the article text is in
    assert text.rstrip().endswith("Krótki artykuł.")


def test_text_pushed_out_by_metadata_counts_as_cut():
    page = link.Page(
        url="http://news.example/a",
        sha256="0" * 64,
        title="T" * 200,
        publisher="P" * 200,
        published_at=None,
        text="A" * (MAX_PAGE_CHARS - 300),
    )
    text, cut = page_text(page)
    assert len(text) <= MAX_PAGE_CHARS and cut


def test_short_page_is_not_cut():
    page = link.Page(
        url="http://news.example/a",
        sha256="0" * 64,
        title="Tytuł",
        publisher="Wydawca",
        published_at=None,
        text="Krótki artykuł. " * 30,
    )
    assert page_text(page)[1] is False


def test_scheme_relative_303_is_followed():
    # The mock serves one canned answer per IP, so the redirect goes to a second host.
    redirect = http(303, body="", headers=["Location: //other.example/final"])
    page, _ = fetch(
        "http://news.example/a",
        {"93.184.216.34": redirect, "93.184.216.35": http()},
    )
    assert page.url == "http://other.example/final"


def test_redirect_to_another_scheme_is_refused():
    redirect = http(302, body="", headers=["Location: ftp://news.example/file"])
    refusal, _ = fetch("http://news.example/a", {"93.184.216.34": redirect})
    assert refusal.message == link.BAD_URL


def test_crashed_worker_is_no_text(tmp_path, monkeypatch):
    worker = tmp_path / "worker.py"
    worker.write_text("raise SystemExit(1)\n")
    monkeypatch.setattr(link, "WORKER", str(worker))
    refusal, _ = fetch("http://news.example/a", {"93.184.216.34": http()})
    assert refusal.message == NO_TEXT


WALL = """<html><head><title>Rząd przyjął projekt</title></head><body><article>
<h1>Rząd przyjął projekt</h1><p>{lead}</p><p>{notice}</p>
<form action="/login" method="post"><input name="email"><input type="password" name="p">
<button>Zaloguj</button></form></article></body></html>"""


@pytest.mark.parametrize(
    "notice",
    [
        "Zaloguj się, aby przeczytać cały artykuł.",
        "Ten artykuł jest dostępny tylko dla subskrybentów.",
        "Subscribe to read the full story.",
    ],
)
def test_inline_access_wall_is_not_checked(notice):
    # No password form and a lead past PREVIEW_CHARS: only the notice can refuse it.
    body = ARTICLE.replace(ARTICLE_TEXT, ARTICLE_TEXT * 5 + "</p><p>" + notice)
    net = FakeNet({"93.184.216.34": http(body=body)})

    def never(messages, info):
        raise AssertionError("model must not be called for a walled page")

    async def guarded_fetch(url):
        return await fetch_page(url, backend=net)

    with pytest.MonkeyPatch.context() as mp, agent.override(model=FunctionModel(never)):
        mp.setattr("prawdowid.verifier.fetch_page", guarded_fetch)
        result = asyncio.run(verify("http://news.example/a"))
    assert result.status is Status.CANNOT_CHECK
    assert result.message == PAYWALL and result.claims == []


def test_password_form_beside_a_preview_is_a_wall():
    body = WALL.format(lead=ARTICLE_TEXT, notice="")
    refusal, _ = fetch("http://news.example/a", {"93.184.216.34": http(body=body)})
    assert refusal.message == PAYWALL


def test_article_quoting_a_login_prompt_is_checked():
    text = (ARTICLE_TEXT + " Oszuści piszą: zaloguj się na stronie banku. ") * 3
    body = ARTICLE.replace(ARTICLE_TEXT, text)
    page, _ = fetch("http://news.example/a", {"93.184.216.34": http(body=body)})
    assert "zaloguj się na stronie banku" in page.text


def test_url_secrets_never_reach_logs_or_the_page(caplog, monkeypatch):
    argv = []
    spawn = asyncio.create_subprocess_exec

    async def record(*args, **kwargs):
        argv.extend(args)
        return await spawn(*args, **kwargs)

    monkeypatch.setattr(link.asyncio, "create_subprocess_exec", record)
    url = (
        "http://news.example/a?id=7&author=Kowalski&token=SECRET1&X-Amz-Signature=SECRET2"
        "&%61pi_key=SECRET4&accessToken=SECRET5&sessionId=SECRET6#access_token=SECRET3"
    )
    with caplog.at_level("INFO", logger="prawdowid"):
        page, _ = fetch(url, {"93.184.216.34": http()})
    assert page.url == (
        "http://news.example/a?id=7&author=Kowalski&token=REDACTED"
        "&X-Amz-Signature=REDACTED&%61pi_key=REDACTED&accessToken=REDACTED&sessionId=REDACTED"
    )
    seen = caplog.text + " ".join(map(str, argv))
    assert "SECRET" not in seen and "news.example" in caplog.text


@pytest.mark.parametrize(
    "url", ["http://user:SECRET@news.example/a", "http://SECRET@news.example/a"]
)
def test_url_with_credentials_is_refused(url, caplog):
    with caplog.at_level("INFO", logger="prawdowid"):
        refusal, net = fetch(url, {"93.184.216.34": http()})
    assert refusal.message == link.CREDENTIALS
    assert net.connected == [] and "SECRET" not in caplog.text


def test_redirect_to_credentials_is_refused():
    redirect = http(302, body="", headers=["Location: http://u:SECRET@other.example/"])
    refusal, net = fetch(
        "http://news.example/a", {"93.184.216.34": redirect, "93.184.216.35": http()}
    )
    assert refusal.message == link.CREDENTIALS
    assert net.connected == ["93.184.216.34"]


def test_paywall_marked_in_microdata_is_not_worked_around():
    meta = '<meta itemprop="isAccessibleForFree" content="false">'
    body = ARTICLE.replace("<article>", "<article>" + meta)
    refusal, _ = fetch("http://news.example/a", {"93.184.216.34": http(body=body)})
    assert refusal.message == PAYWALL


FORM_NOTICE = '<form action="/sub"><p>Subscribe to read the full story.</p><button>Go</button></form>'


def test_free_article_beside_a_newsletter_form_is_checked():
    body = ARTICLE.replace(ARTICLE_TEXT, ARTICLE_TEXT * 5).replace(
        "</article>", "</article>" + FORM_NOTICE
    )
    page, _ = fetch("http://news.example/a", {"93.184.216.34": http(body=body)})
    assert ARTICLE_TEXT.strip() in page.text


def test_subscribe_notice_in_a_small_form_is_a_wall():
    # trafilatura drops a small <form> from its text, so the notice must be read from the HTML.
    body = ARTICLE.replace("</article>", "</article>" + FORM_NOTICE)
    net = FakeNet({"93.184.216.34": http(body=body)})

    def never(messages, info):
        raise AssertionError("model must not be called for a walled page")

    async def guarded_fetch(url):
        return await fetch_page(url, backend=net)

    with pytest.MonkeyPatch.context() as mp, agent.override(model=FunctionModel(never)):
        mp.setattr("prawdowid.verifier.fetch_page", guarded_fetch)
        result = asyncio.run(verify("http://news.example/a"))
    assert result.status is Status.CANNOT_CHECK and result.message == PAYWALL


@pytest.mark.parametrize("name", ["session_id", "session-id", "SESSIONID"])
def test_session_id_spellings_are_secret(name):
    assert link.redact(f"http://news.example/a?{name}=SECRET&id=7") == (
        f"http://news.example/a?{name}=REDACTED&id=7"
    )


def test_url_secrets_never_reach_any_log_record(caplog):
    with caplog.at_level("INFO"):
        page, _ = fetch("http://news.example/a?token=SECRET", {"93.184.216.34": http()})
    assert page.url.endswith("token=REDACTED")
    assert "SECRET" not in caplog.text and "news.example" in caplog.text
