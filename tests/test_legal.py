"""Registers of law, offline: recorded ELI and CELLAR answers through a MockTransport."""

import asyncio
from datetime import date

import httpx2
import pytest

from prawdowid import legal, safefetch

# Shape recorded from GET https://api.sejm.gov.pl/eli/acts/search on 2026-11-22, trimmed.
ELI = {
    "count": 2,
    "items": [
        {
            "address": "WDU20260001099",
            "announcementDate": "2026-07-17",
            "displayAddress": "Dz.U. 2026 poz. 1099",
            "promulgation": "2026-08-18",
            "status": "obowiązujący",
            "title": "Ustawa z dnia 17 lipca 2026 r. o zmianie ustawy o nabywaniu "
            "nieruchomości przez cudzoziemców",
            "entryIntoForce": "2026-11-19",
            "ELI": "DU/2026/1099",
            "textPDF": True,
        },
        {"address": "WDU1", "displayAddress": "Dz.U. bez daty", "title": "Bez daty"},
    ],
}
# Shape recorded from the CELLAR SPARQL endpoint on 2026-11-22, trimmed; title shortened.
CELLAR = {
    "results": {
        "bindings": [
            {
                "celex": {"value": "32025R1214"},
                "title": {
                    "value": "Rozporządzenie (UE) 2025/1214 w sprawie emisji CO2"
                },
                "date": {"value": "2025-06-17"},
                "force": {"value": "1"},
                "eif": {"value": "2025-07-09"},
                "cons": {"value": "02025R1214-20250709"},
            }
        ]
    }
}


EU_TEXT = """<html><body><p>TEKST skonsolidowany, preambuła o emisji CO2 samochodów.</p>
<p>Artykuł\xa01</p><p>Przedmiot</p><p>Rozporządzenie dotyczy wszystkich pojazdów.</p>
<p>Artykuł\xa02</p><p>Od dnia 1\xa0stycznia 2035\xa0r. poziom emisji nowych samochodów
osobowych zmniejsza się o 100%.</p></body></html>"""


def tiny_pdf(text: str) -> bytes:
    """A one-page PDF showing ASCII `text`, offsets computed so pypdf reads it cleanly."""
    stream = f"BT /F1 12 Tf 72 712 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


PL_PDF = tiny_pdf(
    "Art. 1. Komisja liczy glosy. Art. 2. Zaswiadczenie o prawie do glosowania "
    "dolacza sie do spisu wyborcow."
)


@pytest.fixture(autouse=True)
def fresh():
    safefetch._robots.clear()
    legal._parsed.clear()


def transport(
    calls=None, status=200, eli=ELI, cellar=CELLAR, slow=None, pdf=PL_PDF, headers=None
):
    async def handler(request):
        if calls is not None:
            calls.append(request.url)
        if headers is not None:
            headers[request.url.path] = request.headers
        if request.url.path == "/robots.txt":
            return httpx2.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path == slow:
            await asyncio.sleep(1)
        if status != 200 and request.url.host == "api.sejm.gov.pl":
            return httpx2.Response(status)
        if status == 503:  # both registers down
            return httpx2.Response(status)
        if request.url.path == "/eli/acts/search":
            return httpx2.Response(200, json=eli)
        if request.url.path == "/webapi/rdf/sparql":
            return httpx2.Response(200, json=cellar)
        if request.url.path == "/resource/celex/02025R1214-20250709":
            if request.headers.get("accept-language") != "pol":
                return httpx2.Response(400)  # CELLAR negotiates on the language
            return httpx2.Response(
                200, text=EU_TEXT, headers={"content-type": "application/xhtml+xml"}
            )
        if request.url.path == "/eli/acts/DU/2026/1099/text.pdf":
            if "xhtml" in request.headers.get("accept", ""):
                return httpx2.Response(406)  # as the live ELI API does
            return httpx2.Response(
                200, content=pdf, headers={"content-type": "application/pdf"}
            )
        return httpx2.Response(404)

    return httpx2.MockTransport(handler)


def run(queries, t, claim=""):
    return asyncio.run(legal.search_legal(queries, claim, transport=t))


def test_stems_cut_inflection_and_drop_generic_words():
    assert legal.stems("Ustawa o nabywaniu nieruchomości przez cudzoziemców") == [
        "nabywan",
        "nieruch",
        "cudzozi",
    ]
    assert legal.stems("w i o") == []
    assert legal.stems("zakazu handlu w święta") == ["zakazu", "handlu", "święta"]


def test_acts_become_official_documents_with_rendered_text():
    calls = []
    result = run(["nabywanie nieruchomości cudzoziemców"], transport(calls))
    assert result.limitation is None
    pl, eu = result.documents  # the ELI record without a date is dropped
    assert (
        pl.url == "https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20260001099"
    )
    assert pl.source_type == "official" and pl.published_at == date(2026, 8, 18)
    assert (
        "Status: obowiązujący." in pl.text and "Wejście w życie: 2026-11-19." in pl.text
    )
    assert (
        eu.url == "https://eur-lex.europa.eu/legal-content/PL/TXT/?uri=CELEX:32025R1214"
    )
    assert eu.text == (
        "CELEX 32025R1214: Rozporządzenie (UE) 2025/1214 w sprawie emisji CO2. "
        "Data aktu: 2025-06-17. Status: obowiązujący. Wejście w życie: 2025-07-09. "
        "Najnowsza wersja skonsolidowana: CELEX 02025R1214-20250709."
    )
    eli = next(c for c in calls if c.path == "/eli/acts/search")
    assert eli.params["title"] == "nabywan nieruch cudzozi"
    sparql = next(c for c in calls if c.path == "/webapi/rdf/sparql")
    assert "'nabywan*' AND 'nieruch*' AND 'cudzozi*'" in sparql.params["query"]


def test_no_usable_query_asks_nothing():
    calls = []
    assert run(["o w", ""], transport(calls)).documents == []
    assert calls == []


def test_both_registers_failing_is_a_limitation():
    result = run(["handlu niedziele"], transport(status=503))
    assert result.documents == []
    assert result.limitation == legal.LOOKUP_UNAVAILABLE


def test_act_itself_ranks_before_amendments_and_notices():
    def item(pos, title):
        return {
            "address": f"WDU{pos}",
            "displayAddress": f"Dz.U. poz. {pos}",
            "promulgation": "2025-01-01",
            "title": title,
        }

    eli = {
        "items": [
            item(
                301,
                "Obwieszczenie w sprawie ogłoszenia jednolitego tekstu ustawy o handlu",
            ),
            item(2626, "Ustawa o zmianie ustawy o ograniczeniu handlu"),
            item(9, "Ustawa zmieniająca ustawę o handlu"),
            item(305, "Ustawa o ograniczeniu handlu w niedziele"),
        ]
    }
    docs = run(["handlu"], transport(eli=eli, cellar={"results": {"bindings": []}}))
    assert [d.url.rsplit("=", 1)[1] for d in docs.documents] == [
        "WDU305",
        "WDU301",
        "WDU2626",
    ]


def test_one_register_down_keeps_the_others_acts_and_says_so():
    result = run(["emisji samochodów"], transport(status=403))
    assert [d.domain for d in result.documents] == ["eur-lex.europa.eu"]
    assert result.limitation == legal.ELI_UNAVAILABLE


def test_slow_register_does_not_drop_the_other(monkeypatch):
    monkeypatch.setattr(legal, "BUDGET_S", 0.5)
    result = run(["emisji samochodów"], transport(slow="/webapi/rdf/sparql"))
    assert [d.domain for d in result.documents] == ["isap.sejm.gov.pl"]
    assert result.limitation == legal.EU_UNAVAILABLE


def test_malformed_rows_are_skipped():
    eli = {"items": ["not a dict", ELI["items"][0]]}
    cellar = {"results": {"bindings": ["row", {"celex": {"value": 5}}]}}
    result = run(["cudzoziemców"], transport(eli=eli, cellar=cellar))
    assert [d.domain for d in result.documents] == ["isap.sejm.gov.pl"]
    assert result.limitation is None


def test_best_act_in_force_gets_the_articles_closest_to_the_claim():
    seen = {}
    claim = "Od 2035 roku nowe samochody osobowe muszą mieć zerową emisję."
    result = run(["emisji samochodów"], transport(headers=seen), claim)
    pl, eu = result.documents
    version = "CELEX 02025R1214-20250709, wersja skonsolidowana z 2025-07-09"
    assert eu.text.endswith(
        f"Fragmenty tekstu ({version}; bez zmian późniejszych niż ten tekst):\n\n"
        f"[{version}] Artykuł 2 Od dnia 1 stycznia 2035 r. "
        "poziom emisji nowych samochodów osobowych zmniejsza się o 100%."
    )
    # The Polish PDF was asked for without the XHTML Accept (the ELI API answers it 406); no
    # article shares two stems with this claim, so the Polish record stays as it was.
    assert "xhtml" not in seen["/eli/acts/DU/2026/1099/text.pdf"].get("accept", "")
    assert "Fragmenty" not in pl.text


def test_polish_act_text_comes_from_its_pdf():
    claim = (
        "Zaswiadczenie o prawie do glosowania mozna skserowac."  # the PDF font is ASCII
    )
    result = run(["nabywanie nieruchomości"], transport(), claim)
    pl = result.documents[0]
    assert pl.text.endswith(
        "[Dz.U. 2026 poz. 1099, tekst ogłoszony 2026-08-18] Art. 2. Zaswiadczenie o prawie "
        "do glosowania dolacza sie do spisu wyborcow."
    )


def test_unreadable_or_slow_text_leaves_the_record(monkeypatch):
    claim = "Zaświadczenie o prawie do głosowania można skserować."
    broken = run(["nabywanie"], transport(pdf=b"%PDF-1.4 not a pdf"), claim)
    assert "Fragmenty" not in broken.documents[0].text and broken.limitation is None
    monkeypatch.setattr(legal, "TEXT_BUDGET_S", 0.3)
    slow = run(["nabywanie"], transport(slow="/eli/acts/DU/2026/1099/text.pdf"), claim)
    assert "Fragmenty" not in slow.documents[0].text and slow.limitation is None


def test_first_act_in_force_is_read_and_odd_ids_never_are():
    expired = {
        **ELI["items"][0],
        "address": "WDU2",
        "ELI": "DU/2026/2",
        "status": "uchylony",
    }
    odd = {**ELI["items"][0], "address": "WDU3", "ELI": "DU/2026/3?x=1#y"}
    calls = []
    eli = {"items": [expired, odd, ELI["items"][0]]}
    run(["nabywanie"], transport(calls, eli=eli), "Zaświadczenie o głosowaniu")
    texts = [c.path for c in calls if c.path.endswith("text.pdf")]
    assert texts == ["/eli/acts/DU/2026/1099/text.pdf"]
    cellar = {
        "results": {
            "bindings": [
                {**CELLAR["results"]["bindings"][0], "cons": {"value": "0/../x"}}
            ]
        }
    }
    calls = []
    run(["emisji"], transport(calls, cellar=cellar), "emisji samochodów 2035")
    assert not any("/resource/celex/" in c.path for c in calls)


def test_concurrent_claims_parse_one_text_once(monkeypatch):
    parsed = []
    real = legal._text
    monkeypatch.setattr(legal, "_text", lambda *a: parsed.append(1) or real(*a))
    claim = "Zaświadczenie o prawie do głosowania można skserować."

    async def both():
        t = transport()
        return await asyncio.gather(
            *(legal.search_legal(["nabywanie"], claim, transport=t) for _ in range(2))
        )

    first, second = asyncio.run(both())
    assert (
        len(parsed) == 2
    )  # the Polish PDF and the EU XHTML, each once for both claims
    assert first.documents[0].text == second.documents[0].text


def test_passages_weigh_rare_stems_and_numbers():
    text = (
        "Nagłówek obwieszczenia o karcie do głosowania.\n"
        "Art. 1. Karta do głosowania jest drukowana przez komisję.\n"
        "Art. 2. Zaświadczenie o prawie do głosowania dołącza się do spisu wyborców.\n"
        "Art. 3. Karta do głosowania ma 2 strony.\n"
    )
    claim = "Zaświadczenie o prawie do głosowania można skserować."
    assert legal.passages(text, claim) == [
        "Art. 2. Zaświadczenie o prawie do głosowania dołącza się do spisu wyborców."
    ]
    assert legal.passages(text, "Karta do głosowania ma 2 strony.")[-1].startswith(
        "Art. 3."
    )


def test_long_article_is_cut_into_numbered_pieces(monkeypatch):
    monkeypatch.setattr(legal, "MAX_PASSAGE_CHARS", 60)
    article = "Art. 7. § 1. Pierwsze zdanie o wyborach. § 2. Drugie zdanie do 1 maja 2035 r. o spisie."
    pieces = legal._pieces(article)
    assert pieces[0] == "Art. 7. § 1. Pierwsze zdanie o wyborach."
    assert pieces[-1] == "Art. 7. (…) § 2. Drugie zdanie do 1 maja 2035 r. o spisie."
