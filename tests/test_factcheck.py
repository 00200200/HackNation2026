import asyncio
from datetime import date

import httpx2
import pytest

from prawdowid import factcheck
from prawdowid.factcheck import KEY_ENV, LOOKUP_UNAVAILABLE, search_claims

REVIEWED = {
    "claims": [
        {
            "text": "Szczepionki zawierają mikroczipy.",
            "claimReview": [
                {
                    "publisher": {"name": "Demagog", "site": "demagog.org.pl"},
                    "url": "https://demagog.org.pl/fake_news/mikroczipy/",
                    "title": "Mikroczipy w szczepionkach? To fake news",
                    "reviewDate": "2021-03-04T10:00:00Z",
                    "textualRating": "Fałsz",
                    "languageCode": "pl",
                },
                {"publisher": {"name": "No URL"}, "title": "Skipped"},
            ],
        }
    ]
}


def run(handler, **kwargs):
    calls = []

    def record(request):
        calls.append(request)
        return handler(request)

    async def go():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(record)) as client:
            return await search_claims(
                "Szczepionki mają mikroczipy", client=client, **kwargs
            )

    return asyncio.run(go()), calls


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "test-key")


def test_known_claim_returns_its_review_as_a_source():
    lookup, calls = run(lambda r: httpx2.Response(200, json=REVIEWED))

    assert lookup.limitation is None
    [hit] = lookup.hits  # the review without a URL is dropped
    assert hit.rating == "Fałsz"
    assert hit.reviewed_claim == "Szczepionki zawierają mikroczipy."
    assert hit.source.title == "Mikroczipy w szczepionkach? To fake news"
    assert hit.source.publisher == "Demagog"
    assert hit.source.published_at == date(2021, 3, 4)
    assert str(hit.source.url) == "https://demagog.org.pl/fake_news/mikroczipy/"
    assert hit.source.source_type == "fact_check"
    # The rating and the reviewed claim reach rerank and the judge as data.
    assert hit.source.fragment == (
        "Ocena fact-checkera: Fałsz.\n\nSprawdzane twierdzenie: Szczepionki zawierają mikroczipy."
    )

    [request] = calls
    assert request.url.params["query"] == "Szczepionki mają mikroczipy"
    assert request.url.params["languageCode"] == "pl"
    assert request.headers["x-goog-api-key"] == "test-key"
    assert "key" not in request.url.params


def test_no_language_filter():
    _, [request] = run(lambda r: httpx2.Response(200, json={}), language=None)
    assert "languageCode" not in request.url.params


def test_no_match_is_an_empty_result_not_a_limit():
    lookup, _ = run(lambda r: httpx2.Response(200, json={}))
    assert lookup.hits == [] and lookup.limitation is None


def test_missing_key_skips_the_call(monkeypatch):
    monkeypatch.delenv(KEY_ENV)
    lookup, calls = run(lambda r: pytest.fail("no request without a key"))
    assert calls == []
    assert lookup.hits == [] and lookup.limitation == LOOKUP_UNAVAILABLE


@pytest.mark.parametrize("status", [400, 403, 429])
def test_client_errors_are_a_limit_without_retry(status):
    lookup, calls = run(lambda r: httpx2.Response(status, json={"error": {}}))
    assert len(calls) == 1
    assert lookup.hits == [] and lookup.limitation == LOOKUP_UNAVAILABLE


def test_outage_retries_once_then_is_a_limit():
    def down(request):
        raise httpx2.ConnectTimeout("timed out", request=request)

    lookup, calls = run(down)
    assert len(calls) == factcheck.ATTEMPTS == 2
    assert lookup.hits == [] and lookup.limitation == LOOKUP_UNAVAILABLE


def test_retry_recovers_after_a_server_error():
    responses = iter([httpx2.Response(503), httpx2.Response(200, json=REVIEWED)])
    lookup, calls = run(lambda r: next(responses))
    assert len(calls) == 2
    assert len(lookup.hits) == 1 and lookup.limitation is None


@pytest.mark.parametrize(
    "body",
    [
        b"<html>",
        b"[1]",
        b'{"claims": [1]}',
        b'{"claims": [{"claimReview": [{"url": "https://x.pl", "reviewDate": 5}]}]}',
    ],
)
def test_malformed_body_is_a_limit(body):
    lookup, _ = run(lambda r: httpx2.Response(200, content=body))
    assert lookup.hits == [] and lookup.limitation == LOOKUP_UNAVAILABLE


def test_null_lists_are_no_hits():
    lookup, _ = run(lambda r: httpx2.Response(200, json={"claims": None}))
    assert lookup.hits == [] and lookup.limitation is None


def test_broken_encoding_retries_then_is_a_limit():
    def broken(request):
        raise httpx2.DecodingError("bad gzip", request=request)

    lookup, calls = run(broken)
    assert len(calls) == 2
    assert lookup.limitation == LOOKUP_UNAVAILABLE


def test_review_without_title_never_uses_the_claim_as_title():
    body = {
        "claims": [
            {
                "text": "Fałszywe twierdzenie.",
                "claimReview": [{"url": "https://x.pl/a"}],
            }
        ]
    }
    lookup, _ = run(lambda r: httpx2.Response(200, json=body))
    assert lookup.hits[0].source.title == "https://x.pl/a"


def test_trickling_response_hits_the_overall_deadline(monkeypatch):
    # Each chunk arrives well inside the per-read timeout, so only the overall deadline stops it.
    monkeypatch.setattr(factcheck, "DEADLINE_S", 0.2)

    async def trickle():
        for byte in b'{"claims": []}' * 100:
            await asyncio.sleep(0.01)
            yield bytes([byte])

    async def go():
        transport = httpx2.MockTransport(
            lambda r: httpx2.Response(200, content=trickle())
        )
        async with httpx2.AsyncClient(transport=transport) as client:
            loop = asyncio.get_running_loop()
            start = loop.time()
            lookup = await search_claims("x", client=client)
            return lookup, loop.time() - start

    lookup, elapsed = asyncio.run(go())
    assert lookup.hits == [] and lookup.limitation == LOOKUP_UNAVAILABLE
    assert elapsed < 1


def test_review_without_a_rating_has_no_fragment():
    body = {
        "claims": [
            {
                "text": "Szczepionki zawierają mikroczipy.",
                "claimReview": [
                    {"url": "https://demagog.org.pl/x/", "title": "Mikroczipy?"}
                ],
            }
        ]
    }
    lookup, _ = run(lambda r: httpx2.Response(200, json=body))
    assert lookup.hits[0].source.fragment is None


def test_rating_line_is_one_line_with_one_full_stop():
    assert factcheck.review_fragment("Fałsz.\n  Zdjęcie jest z 2015 r..", None) == (
        "Ocena fact-checkera: Fałsz. Zdjęcie jest z 2015 r."
    )
    assert factcheck.review_fragment(" ... ", "Twierdzenie.") is None


# --- #100: several short keys per claim, merged by review URL ---

B01_CLAIM = (
    "Poseł Konrad Berkowicz udostępnił film z podpisem „Ten filmik z Francji przeraża chyba "
    "najbardziej…” jako obraz obecnych protestów we Francji."
)


def test_keys_are_the_claim_its_names_quoted_spans_and_every_query():
    sentence = "Berkowicz pisze: „Ten filmik z Francji przeraża chyba najbardziej…”. A może „tak”?"
    queries = ["Berkowicz film Francja", "berkowicz  FILM francja", "MSWiA protesty"]
    assert (
        factcheck.keys_for(B01_CLAIM, queries, [B01_CLAIM, sentence])
        == [
            B01_CLAIM,
            "Konrad Berkowicz Francji",  # the sentence's first word and the quote's are no names
            "Ten filmik z Francji przeraża chyba najbardziej",  # once, the ellipsis dropped
            "Berkowicz film Francja",  # the same query in other case and spacing goes once
            "MSWiA protesty",
        ]
    )


def test_keys_are_capped():
    queries = [f"zapytanie {i}" for i in range(20)]
    keys = factcheck.keys_for("Twierdzenie.", queries)
    assert len(keys) == factcheck.MAX_KEYS and keys[0] == "Twierdzenie."


@pytest.mark.parametrize(
    "text, names",
    [
        ("Kibice Legii Warszawa poszli pod Trybunał.", "Legii Warszawa Trybunał"),
        ("Najwięcej uchodźców z Ukrainy przeniosło się do Rosji.", "Ukrainy Rosji"),
        ("Polska jest członkiem NATO od 1999 roku.", ""),  # one name matches too much
        ("Rząd podał dane. Według GUS i NBP inflacja spadła.", "GUS NBP"),
    ],
)
def test_names_are_capitalised_words_inside_a_sentence(text, names):
    assert factcheck.names(text) == names


# The reviews behind eval cases B01, C01 and I01 as Fact Check Explorer returned them on
# 2026-11-22, plus a review of a related but different claim (Braun, I01's topic).
INDEX = [
    (
        "Ten filmik z Francji przeraża chyba najbardziej…",
        "Konrad Berkowicz",
        "Protesty we Francji. Berkowicz udostępnia stare nagranie",
        "Manipulacja",
        "https://demagog.org.pl/wypowiedzi/protesty-we-francji-berkowicz-udostepnia-stare-nagranie/",
    ),
    (
        "Pracownik na etacie ma średnio dwa i pół dnia wolne.",
        "Marek Jakubiak",
        "Ile jest dni wolnych w roku? Jankowski kontra Jakubiak",
        "Częściowa prawda",
        "https://demagog.org.pl/wypowiedzi/ile-jest-dni-wolnych-w-roku-jankowski-kontra-jakubiak/",
    ),
    (
        (
            "Najwięcej uchodźców z Ukrainy, ponad 5 milionów, od początku pełnoskalowej "
            "inwazji przeniosło się do Rosji."
        ),
        "Wiele źródeł",
        "Pięć milionów ukraińskich uchodźców trafiło do Rosji? To propaganda Kremla",
        "Fałsz",
        "https://demagog.org.pl/fake_news/piec-milionow-ukrainskich-uchodzcow-trafilo-do-rosji-to-propaganda-kremla/",
    ),
    (
        (
            "Największa liczba [osób – przyp. Demagog] to do Rosji ratowała się, salwowała "
            "się ucieczką z Ukrainy."
        ),
        "Grzegorz Braun",
        "Ukraińscy uchodźcy. Czy Rosja była pierwszym kierunkiem?",
        "Fałsz",
        "https://demagog.org.pl/wypowiedzi/ukrainscy-uchodzcy-czy-rosja-byla-pierwszym-kierunkiem/",
    ),
]


def words(text):
    return set(factcheck.WORD.findall(text.casefold()))


def claim_json(text, claimant, title, rating, url):
    review = {
        "publisher": {"name": "Demagog", "site": "demagog.org.pl"},
        "url": url,
        "title": title,
        "reviewDate": "2026-10-19T00:00:00Z",
        "textualRating": rating,
        "languageCode": "pl",
    }
    return {"text": text, "claimant": claimant, "claimReview": [review]}


def fake_index(request):
    """A review matches only when every word of the query is in its claim, title or claimant."""
    query = words(request.url.params["query"])
    found = [claim_json(*row) for row in INDEX if query <= words(" ".join(row[:3]))]
    return httpx2.Response(
        200, json={"claims": found[: int(request.url.params["pageSize"])]}
    )


def search(handler, claim, keys):
    calls = []

    def record(request):
        calls.append(request)
        return handler(request)

    async def go():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(record)) as client:
            return await factcheck.search_keys(claim, keys, client=client)

    return asyncio.run(go()), calls


@pytest.mark.parametrize(
    "claim, queries, url",
    [
        # The names and the caption find the review; the sentence with its verbs does not.
        (B01_CLAIM, ["Berkowicz udostępnił stary film"], INDEX[0][4]),
        # A web query shares the review's words; the restated sentence does not.
        (
            "Pracownik na etacie średnio co dwa i pół dnia ma dzień wolny.",
            ["ile dni wolnych ma pracownik na etacie", "dni wolne od pracy w Polsce"],
            INDEX[1][4],
        ),
    ],
)
def test_short_keys_find_a_review_the_sentence_misses(claim, queries, url):
    alone, _ = search(fake_index, claim, [claim])
    assert alone.hits == [] and alone.limitation is None

    keys = factcheck.keys_for(claim, queries, [claim])
    lookup, calls = search(fake_index, claim, keys)
    assert [str(h.source.url) for h in lookup.hits] == [
        url
    ]  # once, though several keys found it
    assert lookup.limitation is None
    assert [r.url.params["query"] for r in calls] == keys
    assert {r.url.params["pageSize"] for r in calls} == {str(factcheck.PAGE_SIZE)}
    assert {r.url.params["languageCode"] for r in calls} == {"pl"}


def test_a_name_key_also_brings_reviews_of_other_claims():
    claim = "Najwięcej uchodźców z Ukrainy, ponad 5 milionów, przeniosło się do Rosji."
    lookup, _ = search(fake_index, claim, factcheck.keys_for(claim))
    # Both reach the judge, which tells the review of this claim from Braun's (judge.decide).
    assert {str(h.source.url) for h in lookup.hits} == {INDEX[2][4], INDEX[3][4]}


def test_keys_that_answer_stand_when_others_fail():
    def flaky(request):
        if request.url.params["query"] == "Jakubiak dni wolne":
            return httpx2.Response(429, json={"error": {}})
        return fake_index(request)

    lookup, calls = search(flaky, "x", ["Jakubiak dni wolne", "dni wolnych w roku"])
    assert len(calls) == 2
    assert [str(h.source.url) for h in lookup.hits] == [INDEX[1][4]]
    assert lookup.limitation is None


def test_lookup_is_unavailable_only_when_every_key_failed():
    lookup, calls = search(lambda r: httpx2.Response(403, json={}), "x", ["a b", "c d"])
    assert len(calls) == 2
    assert lookup.hits == [] and lookup.limitation == LOOKUP_UNAVAILABLE


def test_keys_run_at_once_inside_the_deadline(monkeypatch):
    monkeypatch.setattr(factcheck, "DEADLINE_S", 0.3)

    async def slow(request):
        await asyncio.sleep(0.2)
        return httpx2.Response(200, json={})

    async def go():
        transport = httpx2.MockTransport(slow)
        async with httpx2.AsyncClient(transport=transport) as client:
            loop = asyncio.get_running_loop()
            start = loop.time()
            lookup = await factcheck.search_keys(
                "x", ["a", "b", "c", "d"], client=client
            )
            return lookup, loop.time() - start

    lookup, elapsed = asyncio.run(go())
    assert lookup.limitation is None
    assert elapsed < 0.6  # four requests of 0.2 s each, not one after another


def test_one_review_page_rating_two_claims_keeps_the_closer_one():
    url = INDEX[1][4]
    other = claim_json("W roku jest 115 dni wolnych.", "Jankowski", "T", "Prawda", url)
    ours = claim_json(*INDEX[1])
    lookup, _ = search(
        lambda r: httpx2.Response(200, json={"claims": [other, ours]}),
        "Pracownik na etacie średnio co dwa i pół dnia ma dzień wolny.",
        ["dni wolnych w roku"],
    )
    [hit] = lookup.hits
    assert hit.rating == "Częściowa prawda"


def test_merged_hits_take_each_keys_best_first_and_are_capped():
    def per_key(request):
        key = request.url.params["query"]
        found = [
            claim_json(
                f"{key} {i}", "", f"{key} {i}", "Fałsz", f"https://x.pl/{key}/{i}"
            )
            for i in range(factcheck.PAGE_SIZE)
        ]
        return httpx2.Response(200, json={"claims": found})

    lookup, _ = search(per_key, "x", ["a", "b", "c"])
    urls = [str(h.source.url) for h in lookup.hits]
    assert len(urls) == factcheck.MAX_HITS
    assert urls[:3] == ["https://x.pl/a/0", "https://x.pl/b/0", "https://x.pl/c/0"]
