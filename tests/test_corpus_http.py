import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from corpus.http import USER_AGENT, Blocked, Disallowed, FetchError
from tests.corpus_helpers import offline_client

CERT_ROBOTS = "User-agent: *\nDisallow: /\n\nAllow: /$\nAllow: /komunikaty/\n"


def urls(calls) -> list[str]:
    return [str(c.url) for c in calls]


def test_robots_longest_match_allows_only_the_listed_path():
    client = offline_client(
        {
            "https://moje.cert.pl/robots.txt": CERT_ROBOTS,
            "https://moje.cert.pl/komunikaty/2026/1/x/": "<p>komunikat</p>",
            "https://moje.cert.pl/advisories/feed/": "<rss/>",
        }
    )
    assert "komunikat" in client.get("https://moje.cert.pl/komunikaty/2026/1/x/").text
    with pytest.raises(Disallowed, match="robots.txt"):
        client.get("https://moje.cert.pl/advisories/feed/")


def test_a_disallowed_path_is_not_a_block_of_the_whole_site():
    with pytest.raises(Disallowed) as error:
        offline_client({"https://a.pl/robots.txt": "User-agent: *\nDisallow: /x"}).get(
            "https://a.pl/x"
        )
    assert not isinstance(error.value, Blocked)


def test_robots_redirect_is_followed():
    client = offline_client(
        {
            "https://www.gov.pl/robots.txt": (301, "/static/code/robots.txt"),
            "https://www.gov.pl/static/code/robots.txt": "User-agent: *\nDisallow: /private/",
            "https://www.gov.pl/web/a": "ok",
            "https://www.gov.pl/private/a": "secret",
        }
    )
    assert client.get("https://www.gov.pl/web/a").text == "ok"
    with pytest.raises(Disallowed):
        client.get("https://www.gov.pl/private/a")


def test_missing_robots_means_no_rules_but_a_server_error_means_do_not_crawl():
    assert offline_client({"https://a.pl/x": "ok"}).get("https://a.pl/x").text == "ok"
    broken = offline_client(
        {"https://a.pl/robots.txt": (503, ""), "https://a.pl/x": "ok"}
    )
    with pytest.raises(Blocked, match="robots.txt unavailable"):
        broken.get("https://a.pl/x")


def test_unreadable_robots_is_asked_for_once_per_build():
    calls = []
    client = offline_client(
        {
            "https://a.pl/robots.txt": (503, ""),
            "https://a.pl/1": "1",
            "https://a.pl/2": "2",
        },
        calls,
        retries=1,
    )
    for path in ("1", "2"):
        with pytest.raises(Blocked):
            client.get(f"https://a.pl/{path}")
    assert (
        urls(calls) == ["https://a.pl/robots.txt"] * 2
    )  # one try and one retry, then no more


def test_robots_answering_with_a_refusal_blocks_the_site():
    for answer in ((429, ""), '<script src="/_Incapsula_Resource?x"></script>'):
        client = offline_client(
            {"https://a.pl/robots.txt": answer, "https://a.pl/x": "ok"}
        )
        with pytest.raises(Blocked, match="refusal"):
            client.get("https://a.pl/x")


def test_redirect_target_is_checked_against_robots_too():
    client = offline_client(
        {
            "https://a.pl/robots.txt": "User-agent: *\nDisallow: /hidden/",
            "https://a.pl/open": (302, "/hidden/page"),
            "https://a.pl/hidden/page": "secret",
        }
    )
    with pytest.raises(Disallowed):
        client.get("https://a.pl/open")


def test_bot_challenge_and_refusal_are_blocks_and_never_retried():
    calls = []
    challenge = '<html><script src="/_Incapsula_Resource?x=1"></script></html>'
    client = offline_client(
        {
            "https://a.pl/x": challenge,
            "https://a.pl/y": (403, "no"),
            "https://a.pl/z": (429, ""),
            "https://a.pl/w": (202, ""),
        },
        calls,
    )
    for path in ("x", "y", "z", "w"):
        with pytest.raises(Blocked):
            client.get(f"https://a.pl/{path}")
    assert urls(calls).count("https://a.pl/y") == 1
    assert (
        urls(calls).count("https://a.pl/w") == 1
    )  # an empty 202 is a challenge, not "wait"


def test_missing_page_is_an_error_but_not_a_block():
    with pytest.raises(FetchError) as error:
        offline_client({}).get("https://a.pl/gone")
    assert not isinstance(error.value, Blocked)


def test_server_error_is_retried_a_bounded_number_of_times():
    calls = []
    client = offline_client({"https://a.pl/x": (500, "boom")}, calls, retries=2)
    with pytest.raises(FetchError, match="HTTP 500"):
        client.get("https://a.pl/x")
    assert urls(calls).count("https://a.pl/x") == 3


def test_requests_to_one_domain_are_spaced_and_other_domains_are_not_delayed():
    client = offline_client(
        {"https://a.gov.pl/1": "1", "https://a.gov.pl/2": "2", "https://b.pl/1": "3"},
        interval=0.2,
    )
    client.get("https://a.gov.pl/1")  # also fetches robots.txt: two requests, one wait
    start = time.monotonic()
    client.get("https://a.gov.pl/2")
    assert time.monotonic() - start >= 0.18
    start = time.monotonic()
    client.get("https://b.pl/1")  # robots.txt plus the page: one wait, not three
    assert time.monotonic() - start < 0.38


def test_threads_sharing_a_domain_still_wait_their_turn():
    routes = {f"https://a.pl/{n}": str(n) for n in range(4)}
    routes["https://a.pl/robots.txt"] = "User-agent: *\nAllow: /"
    client = offline_client(routes, interval=0.1)
    client.get("https://a.pl/robots.txt", check_robots=False)
    start = time.monotonic()
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(client.get, [f"https://a.pl/{n}" for n in range(4)]))
    assert time.monotonic() - start >= 0.38  # robots.txt and four pages, 0.1 s apart


def test_cache_avoids_a_second_request_until_refresh(tmp_path):
    calls = []
    routes = {"https://a.pl/x": "body"}
    first = offline_client(routes, calls, cache_dir=tmp_path).get("https://a.pl/x")
    seen = len(calls)
    again = offline_client(routes, calls, cache_dir=tmp_path).get("https://a.pl/x")
    assert len(calls) == seen
    assert again == first  # the cached page keeps the time of the real fetch
    offline_client(routes, calls, cache_dir=tmp_path, refresh=True).get(
        "https://a.pl/x"
    )
    assert len(calls) > seen


def test_cached_page_older_than_max_age_is_fetched_again(tmp_path):
    calls = []
    routes = {"https://a.pl/list": "new list"}
    client = offline_client(routes, calls, cache_dir=tmp_path)
    client.get("https://a.pl/list")
    entry = next(tmp_path.glob("*.json"))
    old = json.loads(entry.read_text())
    old["fetched_at"] = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    entry.write_text(json.dumps(old))
    seen = len(calls)
    assert (
        client.get("https://a.pl/list", max_age=3 * 3600).fetched_at
        == old["fetched_at"]
    )
    assert len(calls) == seen
    assert client.get("https://a.pl/list", max_age=3600).fetched_at != old["fetched_at"]
    assert len(calls) == seen + 1


def test_broken_cache_entry_is_a_miss(tmp_path):
    client = offline_client({"https://a.pl/x": "fresh"}, cache_dir=tmp_path)
    client.get("https://a.pl/x")
    entry = next(tmp_path.glob("*.json"))
    for broken in (
        b'{"url": "https://a.pl/x", "te',
        b"\xff\xfe",
        b'{"url": "u", "text": "t", "content_type": "", "fetched_at": "wczoraj"}',
    ):
        entry.write_bytes(broken)
        assert client.get("https://a.pl/x", max_age=60).text == "fresh"


def test_api_key_travels_in_a_header_and_never_reaches_the_cache(tmp_path):
    calls = []
    client = offline_client({"https://api.pl/q?a=1": "{}"}, calls, cache_dir=tmp_path)
    client.get(
        "https://api.pl/q?a=1", headers={"X-Goog-Api-Key": "s3cret"}, check_robots=False
    )
    assert urls(calls) == ["https://api.pl/q?a=1"]  # no robots.txt request
    assert calls[0].headers["x-goog-api-key"] == "s3cret"
    assert all("s3cret" not in f.read_text() for f in tmp_path.iterdir())


def test_headers_are_not_forwarded_when_a_redirect_leaves_the_origin():
    calls = []
    client = offline_client(
        {"https://api.pl/q": (302, "https://other.pl/r"), "https://other.pl/r": "{}"},
        calls,
    )
    client.get(
        "https://api.pl/q", headers={"X-Goog-Api-Key": "s3cret"}, check_robots=False
    )
    sent = {str(c.url): c.headers.get("x-goog-api-key") for c in calls}
    assert sent == {"https://api.pl/q": "s3cret", "https://other.pl/r": None}


def test_user_agent_is_generic():
    calls = []
    offline_client({"https://a.pl/x": "ok"}, calls).get("https://a.pl/x")
    assert calls[0].headers["user-agent"] == USER_AGENT
    assert "@" not in USER_AGENT


def test_get_json_parses_the_body():
    client = offline_client({"https://a.pl/data": json.dumps({"items": [1]})})
    assert client.get_json("https://a.pl/data") == {"items": [1]}
