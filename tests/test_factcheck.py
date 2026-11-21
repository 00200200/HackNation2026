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
    # The reviewed claim is the disputed statement, never shown as the source's quote.
    assert hit.source.fragment is None

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
