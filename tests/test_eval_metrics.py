import json

import pytest

from evals import adapter, metrics, run


def resp(verdict, evidence=None, status="ok"):
    return {
        "status": status,
        "claims": [{"verdict": verdict, "evidence": evidence or []}],
    }


def test_macro_f1_perfect_and_partial():
    gold = ["potwierdzone", "fałszywe", "potwierdzone"]
    assert metrics.macro_f1(gold, gold) == 1.0
    assert (
        metrics.macro_f1(gold, ["potwierdzone", "potwierdzone", "potwierdzone"]) == 0.4
    )
    assert metrics.macro_f1([], []) is None


def test_non_ok_status_is_never_a_verdict():
    assert (
        metrics.predicted_verdict({"status": "technical_error"})
        == "status:technical_error"
    )
    assert metrics.predicted_verdict(resp("fałszywe")) == "fałszywe"


def test_citation_coverage_counts_factual_verdicts_only():
    cited = [{"url": "https://a.pl", "quote": "tekst"}]
    responses = [
        resp("potwierdzone", cited),
        resp("fałszywe"),
        resp("brak wystarczających dowodów"),
    ]
    assert metrics.citation_coverage(responses) == 0.5


def test_citation_correctness_needs_verbatim_quote():
    corpus = {"https://a.pl": "Polska   przystąpiła do NATO w 1999 roku."}
    good = resp(
        "potwierdzone", [{"url": "https://a.pl", "quote": "przystąpiła do NATO"}]
    )
    bad = resp("potwierdzone", [{"url": "https://a.pl", "quote": "w 2004 roku"}])
    assert metrics.citation_correctness([good, bad], corpus) == 0.5
    assert metrics.citation_correctness([good], None) is None


def test_citation_correctness_scores_only_corpus_urls():
    corpus = {"https://a.pl": "Polska przystąpiła do NATO w 1999 roku."}
    web = resp(
        "potwierdzone", [{"url": "https://web.pl/x", "quote": "cytat ze strony"}]
    )
    good = resp(
        "potwierdzone", [{"url": "https://a.pl", "quote": "przystąpiła do NATO"}]
    )
    # A web page outside the corpus is unmeasured, not wrong.
    assert metrics.citation_correctness([web, good], corpus) == 1.0
    assert metrics.citation_correctness([web], corpus) is None


def test_check_handles_unknown_and_both_directions():
    assert metrics.check("macro_f1", None)["pass"] is None
    assert metrics.check("macro_f1", 0.8)["pass"] is True
    assert metrics.check("median_latency_s", 31.0)["pass"] is False


def test_adapter_maps_check_result_to_eval_shape():
    raw = {
        "status": "ok",
        "claims": [
            {
                "claim": "Polska jest w NATO od 1999 r.",
                "source_sentence": "Polska jest w NATO od 1999 r.",
                "reasoning": "Uzasadnienie.",
                "verdict": "confirmed",
                "verdict_label": "potwierdzone",
                "sources": [
                    {
                        "title": "T",
                        "publisher": "P",
                        "published_at": "1999-03-12",
                        "url": "https://a.pl/x",
                        "fragment": "przystąpiła do NATO",
                    }
                ],
            }
        ],
        "unchecked_claims": ["Inne twierdzenie."],
        "security_events": [
            {"kind": "prompt_injection", "location": "input", "detector": "model"}
        ],
        "cost_usd": 0.014,
    }
    shaped = adapter.to_eval_shape(raw)
    assert shaped["security_events"] == raw["security_events"]
    assert shaped["cost_usd"] == 0.014
    # Everything the UI shows reaches the canary check.
    assert shaped["claims"][0]["source_sentence"] == "Polska jest w NATO od 1999 r."
    assert shaped["claims"][0]["reasoning"] == "Uzasadnienie."
    assert shaped["unchecked_claims"] == ["Inne twierdzenie."]
    assert shaped["claims"][0]["verdict"] == "potwierdzone"
    assert shaped["claims"][0]["evidence"][0] == {
        "title": "T",
        "publisher": "P",
        "published_at": "1999-03-12",
        "url": "https://a.pl/x",
        "quote": "przystąpiła do NATO",
    }
    assert adapter.to_eval_shape({"status": "cannot_check", "message": "m"}) == {
        "status": "cannot_check",
        "message": "m",
        "claims": [],
        "unchecked_claims": [],
    }
    assert (
        adapter.to_eval_shape({"claims": [{"verdict": "false"}]})["claims"][0][
            "verdict"
        ]
        == "fałszywe"
    )


class FakeHttpResponse:
    def __init__(self, headers):
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b'{"claims": []}'


@pytest.mark.parametrize(
    ("headers", "cached"), [({"X-Cache": "hit"}, True), ({}, False)]
)
def test_adapter_marks_an_answer_taken_from_the_result_cache(
    monkeypatch, headers, cached
):
    monkeypatch.setenv("PRAWDOWID_URL", "http://product.test")
    monkeypatch.setattr(
        adapter.urllib.request,
        "urlopen",
        lambda request, timeout: FakeHttpResponse(headers),
    )
    assert adapter.ask({"text": "x"}, "web")["cached"] is cached


def test_demo_channel_sends_the_request_of_the_czat_page(monkeypatch):
    """PRAWDOWID_EXTRA_CHANNELS=demo (#116): a scenario G case also runs as the /czat demo
    adapter, the web request with X-Channel: demo; Discord runs only when it is listed too."""
    sent = []

    def urlopen(request, timeout):
        sent.append(request)
        return FakeHttpResponse({})

    monkeypatch.setenv("PRAWDOWID_URL", "http://product.test")
    monkeypatch.setattr(adapter.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(adapter, "CHANNELS", {"web", "demo"})
    monkeypatch.setattr(adapter, "wait_turn", lambda: None)
    case = {"id": "G1", "input": {"text": "x"}, "channels": ["web", "discord", "demo"]}
    row = run.run_case(case)
    assert [r["channel"] for r in row["runs"]] == ["web", "demo"]
    # urllib keeps header names capitalised this way.
    assert [r.get_header("X-channel") for r in sent] == ["web", "demo"]


@pytest.mark.parametrize(
    "raw",
    [
        {"status": "cannot_check", "message": "CANARY-7"},
        {"claims": [{"premises": ["Brakujący kontekst: CANARY-7"]}]},
        {"claims": [{"limitations": ["CANARY-7"]}]},
    ],
)
def test_text_the_user_sees_reaches_the_canary_check(raw):
    assert "CANARY-7" in json.dumps(adapter.to_eval_shape(raw))


def test_citation_correctness_matches_a_url_written_another_way():
    corpus = {"https://www.a.pl/x/": "Polska przystąpiła do NATO w 1999 roku."}
    good = resp(
        "potwierdzone", [{"url": "http://a.pl/x", "quote": "przystąpiła do NATO"}]
    )
    assert metrics.citation_correctness([good], corpus) == 1.0


def test_citation_correctness_keeps_every_text_of_one_canonical_url():
    # Two corpus records, one canonical URL, different text: a quote from either is correct, and
    # the order of the records does not matter.
    records = [
        ("https://www.a.pl/x/", "Polska przystąpiła do NATO w 1999 roku."),
        ("http://a.pl/x", "Polska przystąpiła do UE w 2004 roku."),
    ]
    evidence = [
        {"url": "https://a.pl/x", "quote": "przystąpiła do NATO"},
        {"url": "https://a.pl/x", "quote": "przystąpiła do UE"},
    ]
    wrong = [{"url": "https://a.pl/x", "quote": "w 2010 roku"}]
    for corpus in (dict(records), dict(reversed(records))):
        assert (
            metrics.citation_correctness([resp("potwierdzone", evidence)], corpus)
            == 1.0
        )
        both = [resp("potwierdzone", evidence), resp("potwierdzone", wrong)]
        assert metrics.citation_correctness(both, corpus) == pytest.approx(2 / 3)
