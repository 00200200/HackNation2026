"""Steps 2 to 5 for one claim, under the time budget of the whole check.

Step 2 runs five lookups at once: 2a Google Fact Check (`factcheck.search_keys`, the claim and its
short keys from `factcheck.keys_for`), EUvsDisinfo
known narratives (`euvsdisinfo.search_cases`, context that never decides alone), the www.gov.pl
site search (`govpl.search_govpl`, the claim's gov.pl queries, else its first web query; off with
PRAWDOWID_GOVPL=0), 2b web search and fetch (`websearch.search_web`, one search per web query of
the claim, www.gov.pl pages left to the gov.pl lookup) and our evidence corpus
(`corpus_bm25.search_evidence`: BM25 over `corpus/evidence.jsonl`, the claim and all its queries).
Step 2c (our own database, #19) is out of the pipeline for now (team decision). Any EUvsDisinfo
source, whichever lookup found it, is context only. The candidates go to step 3 (`rerank.rerank`, the linked page left out) and
steps 4 and 5 (`judge.judge`, verdict from `decide()`). When the evidence is not enough and time
remains, the web is searched once more with a rewritten query and the claim is judged again.

A source that fails adds a limitation. The sources that can decide a verdict (Fact Check, web
search) are the ones whose outage matters: when one of them failed and the evidence is not enough,
when every source failed, or when the judge did not answer, the claim is not checked and the
outage is the reason, never "brak wystarczających dowodów" (`ClaimCheck.outage`, which turns an
all-outage answer into a technical error). Fact Check failed when the claim's own key or every key
failed (`FactCheckLookup.failed`), web search when every query failed (`WebSearch.failed`); a
failed key or query among others that answered is a limitation only. The corpus is a file on our
own disk, so it never counts as a source that answered: when every outside source failed, corpus
hits count only if they settle the claim, otherwise it is not checked. A claim that runs out of time is not checked either, and
keeps the limitations of the sources that had already failed. Every step's time goes to the log;
the reranker and judge calls are priced like the extraction call.

Retrieved pages are screened for instructions in code (`_source_events`, the same patterns as the
user's text), whatever the models do: an injection is logged even when rerank drops the page
before the judge sees it, or the claim is cut by the time limit.
"""

import asyncio
import logging
import os
import time

from pydantic import BaseModel
from pydantic_ai import ModelResponse, capture_run_messages
from pydantic_ai.messages import ModelMessage, ModelRequest

from prawdowid import (
    corpus_bm25,
    euvsdisinfo,
    factcheck,
    faults,
    govpl,
    judge,
    rerank,
    websearch,
)
from prawdowid.contract import ModelCall, SecurityEvent, Source, Verdict

log = logging.getLogger("prawdowid")

# Hyperparameters, first guesses for the 30 s median, not tuned.
# Whole check, from the request to the last verdict (the API gives up at 60 s, nginx at 75 s).
# 25 s left a long page with no judged claim (#63): extraction alone takes much of it.
CHECK_BUDGET_S = float(os.getenv("PRAWDOWID_CHECK_BUDGET_S") or 40)
# The retry starts only with at least this much time left: a web search, rerank and judge again.
RETRY_MIN_S = float(os.getenv("PRAWDOWID_RETRY_MIN_S") or 18)
# EUvsDisinfo only adds context: it may not hold up the claim for its own 15 s deadline.
EUVSDISINFO_BUDGET_S = float(os.getenv("PRAWDOWID_EUVSDISINFO_BUDGET_S") or 5)
# The API builds the corpus index at startup (about a second, more on a small server); a lookup
# that finds it ready takes a millisecond, one that comes first builds it while the web lookups run.
CORPUS_BUDGET_S = 5

TIME_LIMIT = (
    "Nie sprawdzono: skończył się czas przeznaczony na sprawdzenie ({budget:g} s). "
    "Spróbuj sprawdzić to twierdzenie osobno."
)
WEB_PARTIAL = (
    "Część wyszukiwań w sieci ({failed} z {total}) nie zwróciła wyników albo się nie powiodła, "
    "więc źródła mogą być niepełne."
)
DISINFO_DATABASE = websearch.ALLOWLIST["euvsdisinfo.eu"].source_type
RETRY_UNJUDGED = (
    "Dodatkowe wyszukiwanie znalazło strony, ale model nie zdążył ich ocenić, "
    "więc ocena opiera się tylko na pierwszym wyszukiwaniu."
)
FACTCHECK_DOWN = "bazy Google Fact Check"
WEB_DOWN = "wyszukiwarki internetowej"
GOVPL_DOWN = "wyszukiwarki portalu www.gov.pl"
OUTAGE = (
    "Nie mogę teraz sprawdzić {what} z powodu błędu dostępu. To awaria techniczna, "
    "a nie wynik sprawdzenia: nie wydajemy werdyktu, a brak odpowiedzi nie znaczy, "
    "że nic nie znaleziono."
)
SOURCES_FAILED = (
    "Nie mogę teraz sprawdzić tego twierdzenia: żadne źródło nie odpowiedziało ani nie dało się "
    "odczytać. To awaria techniczna, a nie wynik sprawdzenia: nie wydajemy werdyktu."
)


class ClaimCheck(BaseModel):
    judgement: judge.Judgement
    # Reranker and judge calls; None when a request may be billed but its price is unknown.
    cost_usd: float | None
    steps_ms: dict[str, int]
    model_calls: list[ModelCall] = []
    # The claim is not checked because a source or the model was down: a technical failure of
    # the check, not a time limit.
    outage: bool = False


async def check_claim(
    claim: str,
    queries: list[str],
    deadline: float,
    exclude_url: str | None = None,
    govpl_queries: list[str] = (),
    source_sentence: str = "",
) -> ClaimCheck:
    """Verdict for one claim. `deadline` is `loop.time()` when the whole check must end.

    `queries` go to web search, `govpl_queries` to the gov.pl site search (to the web when it is
    switched off). Fact Check gets the claim and short keys: both kinds of queries, the names in
    the claim and spans in quotation marks in the claim or `source_sentence`.
    """
    steps: dict[str, int] = {}
    # Before the gov.pl switch below folds its queries into the web ones.
    factcheck_keys = factcheck.keys_for(
        claim, [*queries, *govpl_queries], [claim, source_sentence]
    )
    # Messages of each reranker and judge run, priced and logged in `_done`.
    runs: list[list[ModelMessage]] = []
    # Each lookup's answer as soon as it arrives, so a time limit keeps what already failed.
    found: dict = {"web": []}
    if govpl.ENABLED:
        # Keywords suit the gov.pl search box better than the claim sentence.
        gov = [q for q in govpl_queries if q.strip()]
        gov = gov or [q for q in queries if q.strip()][:1] or [claim]
    else:
        gov, queries = None, [*queries, *govpl_queries]
    searched = queries or [claim]
    if _now() >= deadline:  # nothing is started after the budget ran out
        return _done(claim, _time_limit(found), runs, steps)
    try:
        async with asyncio.timeout_at(deadline):
            await _retrieve(claim, searched, gov, steps, found, factcheck_keys)
            candidates = _candidates(found)
            judgement = await _judge(claim, candidates, exclude_url, steps, runs)
    except TimeoutError:
        # The cost is None for a model request cut mid-flight, 0 when only search was cut.
        timed_out = _time_limit(found)
        # The pattern pre-check needs no model: pages already found are still screened.
        timed_out.security_events = _source_events(_candidates(found), exclude_url)
        return _done(claim, timed_out, runs, steps)
    # Instructions in retrieved pages, kept from both passes: the pattern pre-check on every
    # candidate (rerank may drop it before the judge sees it) and the judge's own flag.
    events = [*_source_events(candidates, exclude_url), *judgement.security_events]

    cut = False
    # The claim itself is the rewritten query, so no retry when it was searched already.
    retry = claim not in searched
    if retry and _needs_more(judgement) and deadline - _now() >= RETRY_MIN_S:
        try:
            async with asyncio.timeout_at(deadline):
                # ponytail: the claim itself is the rewritten query (the first pass used the
                # model's queries); a HyDE-FC rewrite costs one more model call per claim.
                web = await _timed(steps, "retry_web", _search_web, claim)
                if web.documents:
                    fresh = _candidates({"web": [web]})
                    # Screened before the retry judge, which may time out or fail.
                    events += _source_events(fresh, exclude_url)
                    more = candidates + fresh
                    second = await _judge(
                        claim, more, exclude_url, steps, runs, "retry_"
                    )
                    # The first pass assessed evidence only when it had fragments left after
                    # rerank (the linked page excluded): otherwise there is no verdict to keep.
                    assessed = judge.NO_FRAGMENTS not in judgement.limitations
                    if second.verdict is Verdict.NOT_CHECKED and assessed:
                        # The retry judge failed: the verdict from the first pass's evidence
                        # stands, judged without the extra pages.
                        judgement.limitations.append(RETRY_UNJUDGED)
                    else:
                        judgement = second
                        events += judgement.security_events
                        candidates = more
                # Only a finished retry counts: a cut one keeps the first pass as it was.
                found["web"].append(web)
        except TimeoutError:
            log.info("retry cut by the time limit claim=%r", claim)
            cut = True

    limits = _limits(found)
    outage = judgement.verdict is Verdict.NOT_CHECKED  # the judge did not answer
    down = _deciders_down(found, govpl_decides=bool(govpl_queries))
    # The corpus is a file on our disk and says nothing about the outside sources: when all of
    # them failed, it counts only if it settled the claim, else the claim is not checked.
    outside = {name: lookup for name, lookup in found.items() if name != "corpus"}
    every_source_failed = set(outside) <= set(limits) and not _candidates(outside)
    if every_source_failed and (
        not candidates or judgement.verdict is Verdict.INSUFFICIENT_EVIDENCE
    ):
        outage = not cut
        reason = TIME_LIMIT.format(budget=CHECK_BUDGET_S) if cut else SOURCES_FAILED
        judgement = _not_checked(reason)
    elif down and _needs_more(judgement):
        # Not "no evidence exists": the source that could have had it did not answer.
        outage = True
        judgement = _not_checked(OUTAGE.format(what=" ani ".join(down)))
    # The main reason first, then what each source said.
    reasons = judgement.limitations if judgement.verdict is Verdict.NOT_CHECKED else []
    judgement.limitations = list(
        dict.fromkeys([*reasons, *limits.values(), *judgement.limitations])
    )
    judgement.security_events = events[:1]  # same kind and location: one is enough
    return _done(claim, judgement, runs, steps, outage)


async def _retrieve(
    claim: str,
    queries: list[str],
    gov: list[str] | None,
    steps: dict[str, int],
    found: dict,
    factcheck_keys: list[str] = (),
) -> None:
    """Steps 2a (every key in `factcheck_keys` at once, the claim when there are none),
    EUvsDisinfo, gov.pl (when `gov` is set), 2b and the corpus at once, each answer stored in
    `found` as it arrives.

    TaskGroup: when the time limit cuts the claim, every lookup task still running is cancelled
    and awaited before this returns. Provider threads (`asyncio.to_thread`) cannot be cancelled:
    they finish in the background, bounded by their own timeouts.
    """

    async def keep(name, fn):
        found[name] = await _timed(steps, name, fn, claim)

    async def web(query):
        found["web"].append(await _search_web(query))

    async def all_web():
        async with asyncio.TaskGroup() as tg:
            for query in queries:
                tg.create_task(web(query))

    # The corpus gets every wording: the rankings of the claim and of each query are merged.
    corpus_queries = list(dict.fromkeys([claim, *queries, *(gov or [])]))
    async with asyncio.TaskGroup() as tg:
        tg.create_task(
            keep(
                "factcheck", lambda _: _search_claims(claim, factcheck_keys or [claim])
            )
        )
        tg.create_task(keep("euvsdisinfo", _search_cases))
        tg.create_task(_timed(steps, "web", all_web))
        tg.create_task(keep("corpus", lambda _: _search_corpus(corpus_queries)))
        if gov is not None:
            tg.create_task(keep("govpl", lambda _: _search_govpl(gov)))
        # Step 2c (`cache.search_documents`, #19) plugs in here when it is back in the pipeline.


def _candidates(found: dict) -> list[Source]:
    webs = [*found["web"], found.get("govpl", websearch.WebSearch())]
    pages = [d.to_source(fragment=d.text) for w in webs for d in w.documents]
    # A page fetched in this check beats its stored copy: rerank keeps the first source per URL.
    live = {rerank.canonical_url(str(p.url)) for p in pages}
    sources = [
        h.source
        for name in ("factcheck", "euvsdisinfo", "corpus")
        if name in found
        for h in found[name].hits
        if name != "corpus" or rerank.canonical_url(str(h.source.url)) not in live
    ]
    # The corpus comes before the web: past MAX_DOCUMENTS the web's tail is cut, not its hits.
    return [_context_only(s) for s in [*sources, *pages]]


def _source_events(
    sources: list[Source], exclude_url: str | None
) -> list[SecurityEvent]:
    """Pattern pre-check on retrieved sources; the linked page itself is logged as `page`."""
    from prawdowid.verifier import screen  # verifier imports this module

    skip = exclude_url and rerank.canonical_url(exclude_url)
    for source in sources:  # one event per check is enough
        if skip and rerank.canonical_url(str(source.url)) == skip:
            continue
        if events := screen(f"{source.title}\n{source.fragment or ''}", "source"):
            return events
    return []


def _context_only(source: Source) -> Source:
    """Any EUvsDisinfo source is a known-narrative match, whichever lookup found it (a Google
    ClaimReview from euvsdisinfo.eu comes typed `fact_check`): context, never reliable alone."""
    entry = websearch.allowed(str(source.url))
    if (entry and entry.source_type == DISINFO_DATABASE) or (
        "euvsdisinfo" in source.publisher.casefold()
    ):
        return source.model_copy(update={"source_type": DISINFO_DATABASE})
    return source


def _limits(found: dict) -> dict[str, str]:
    """The limitation of each source that failed; a web query that failed is kept even when
    another one found pages."""
    # ponytail: counts finished queries only; on a time limit the cut ones are not counted, and
    # TIME_LIMIT comes first anyway.
    webs = found["web"]
    failed = [w.limitation for w in webs if w.limitation]
    if failed and len(failed) == len(webs):
        web = failed[0]
    elif failed:
        web = WEB_PARTIAL.format(failed=len(failed), total=len(webs))
    else:
        web = None
    limits = {
        "factcheck": found["factcheck"].limitation if "factcheck" in found else None,
        "euvsdisinfo": found["euvsdisinfo"].limitation
        if "euvsdisinfo" in found
        else None,
        "govpl": found["govpl"].limitation if "govpl" in found else None,
        "web": web,
        "corpus": found["corpus"].limitation if "corpus" in found else None,
    }
    return {k: v for k, v in limits.items() if v}


def _deciders_down(found: dict, govpl_decides: bool) -> list[str]:
    """The sources that can decide a verdict and failed (not: answered with no hits). The gov.pl
    search decides only for a claim about the Polish government (the model gave it gov.pl queries);
    web search leaves www.gov.pl to it."""
    down = []
    # The claim's own key or every key failed: a failed name or query key alone is a limitation.
    if "factcheck" in found and found["factcheck"].failed:
        down.append(FACTCHECK_DOWN)
    # Every query failed at the provider: one query that found nothing is an answer.
    if found["web"] and all(w.failed for w in found["web"]):
        down.append(WEB_DOWN)
    if govpl_decides and "govpl" in found and found["govpl"].limitation:
        down.append(GOVPL_DOWN)
    return down


def _time_limit(found: dict) -> judge.Judgement:
    judgement = _not_checked(TIME_LIMIT.format(budget=CHECK_BUDGET_S))
    judgement.limitations += _limits(found).values()
    return judgement


async def _search_web(query: str) -> websearch.WebSearch:
    """An unexpected error (cache write, extraction) is a limitation of this source only."""
    try:
        # Bounded inside: search by SEARCH_BUDGET_S, each page by PAGE_BUDGET_S.
        return await websearch.search_web(
            query, skip_hosts=govpl.HOSTS if govpl.ENABLED else frozenset()
        )
    except Exception:
        log.exception("web search failed query=%r", query)
        return websearch.WebSearch(limitation=websearch.SEARCH_UNAVAILABLE, failed=True)


async def _search_govpl(queries: list[str]) -> websearch.WebSearch:
    try:
        return await govpl.search_govpl(queries)
    except Exception:
        log.exception("gov.pl search failed")
        return websearch.WebSearch(limitation=govpl.LOOKUP_UNAVAILABLE)


async def _search_claims(claim: str, keys: list[str]) -> factcheck.FactCheckLookup:
    # Eval traffic only (see faults.py): every key fails, so none is sent.
    if faults.active(faults.FACTCHECK_UNAVAILABLE):
        return factcheck.unavailable()
    try:
        return await factcheck.search_keys(claim, keys)
    except Exception:
        log.exception("factcheck failed")
        return factcheck.unavailable()


async def _search_cases(claim: str) -> euvsdisinfo.EuvsdisinfoLookup:
    try:
        return await asyncio.wait_for(
            euvsdisinfo.search_cases(claim), EUVSDISINFO_BUDGET_S
        )
    except Exception:  # TimeoutError of its own budget included
        log.exception("euvsdisinfo failed")
        return euvsdisinfo.EuvsdisinfoLookup(limitation=euvsdisinfo.LOOKUP_UNAVAILABLE)


async def _search_corpus(queries: list[str]) -> corpus_bm25.EvidenceLookup:
    try:
        return await asyncio.wait_for(
            corpus_bm25.search_evidence(queries), CORPUS_BUDGET_S
        )
    except Exception:  # TimeoutError of its own budget included
        log.exception("corpus search failed")
        return corpus_bm25.EvidenceLookup(limitation=corpus_bm25.CORPUS_UNAVAILABLE)


async def _judge(
    claim: str,
    candidates: list[Source],
    exclude_url: str | None,
    steps: dict[str, int],
    runs: list[list[ModelMessage]],
    prefix: str = "",
) -> judge.Judgement:
    """Steps 3 to 5. The linked page is never evidence for its own claims."""
    ranking = await _priced(
        runs,
        _timed(
            steps,
            prefix + "rerank",
            rerank.rerank,
            claim,
            candidates,
            exclude_url=exclude_url,
        ),
    )
    judgement = await _priced(
        runs, _timed(steps, prefix + "judge", judge.judge, claim, ranking)
    )
    if judge.JUDGE_UNAVAILABLE in judgement.limitations:
        # The judge did not answer: a technical limit, never "brak wystarczających dowodów".
        return _not_checked(judge.JUDGE_UNAVAILABLE).model_copy(
            update={
                "limitations": list(
                    dict.fromkeys([judge.JUDGE_UNAVAILABLE, *judgement.limitations])
                )
            }
        )
    return judgement


async def _priced(runs: list[list[ModelMessage]], aw):
    """Keeps the messages of the model run inside `aw` in `runs`, also when the time limit cuts
    it: a request without an answer may be billed, so its price is unknown (None)."""
    with capture_run_messages() as messages:
        try:
            return await aw
        finally:
            runs.append(messages)


def _needs_more(judgement: judge.Judgement) -> bool:
    """Not enough evidence, and not because sources disagree."""
    return (
        judgement.verdict is Verdict.INSUFFICIENT_EVIDENCE
        and judge.CONFLICT not in judgement.limitations
    )


def _cost(messages: list[ModelMessage]) -> float | None:
    """Price of the captured run: 0.0 without a request, None when a request got no priced
    answer (failed, cut off or an unpriced model)."""
    responses = [m for m in messages if isinstance(m, ModelResponse)]
    requests = [m for m in messages if isinstance(m, ModelRequest)]
    if len(requests) > len(responses):
        return None
    try:
        return sum(float(r.cost().total_price) for r in responses)
    except (LookupError, ValueError):
        return None


async def _timed(steps: dict[str, int], name: str, fn, *args, **kwargs):
    """Runs `fn(*args, **kwargs)` and records its time. The coroutine is made here, so a task
    cancelled before it starts leaves no coroutine behind that was never awaited."""
    started = time.perf_counter()
    try:
        return await fn(*args, **kwargs)
    finally:
        steps[name] = round((time.perf_counter() - started) * 1000)


def _now() -> float:
    return asyncio.get_running_loop().time()


def _not_checked(limitation: str) -> judge.Judgement:
    return judge.Judgement(
        verdict=Verdict.NOT_CHECKED,
        strength="brak",
        premises=[],
        sources=[],
        limitations=[limitation],
    )


def _done(
    claim: str,
    judgement: judge.Judgement,
    runs: list[list[ModelMessage]],
    steps: dict[str, int],
    outage: bool = False,
) -> ClaimCheck:
    costs = [_cost(m) for m in runs]
    cost = None if None in costs else sum(costs)
    log.info(
        "claim check claim=%r verdict=%s sources=%d cost_usd=%s steps_ms=%s",
        claim,
        judgement.verdict,
        len(judgement.sources),
        cost,
        steps,
    )
    return ClaimCheck(
        judgement=judgement,
        cost_usd=cost,
        steps_ms=steps,
        outage=outage,
        model_calls=[
            model_call(r) for m in runs for r in m if isinstance(r, ModelResponse)
        ],
    )


def model_call(response: ModelResponse) -> ModelCall:
    return ModelCall(
        model=response.model_name,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
