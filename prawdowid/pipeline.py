"""Steps 2 to 5 for one claim, under the time budget of the whole check.

Step 2 runs up to five lookups at once: 2a Google Fact Check (`factcheck.search_claims`), EUvsDisinfo
known narratives (`euvsdisinfo.search_cases`, context that never decides alone), the www.gov.pl
site search (`govpl.search_govpl`, the claim's gov.pl queries, else its first web query; off with
PRAWDOWID_GOVPL=0), the registers of law (`legal.search_legal`, ISAP/ELI and EUR-Lex, only for a
claim with legal queries; off with PRAWDOWID_LEGAL=0) and 2b web search and fetch (`websearch.search_web`, one search per web query of
the claim, www.gov.pl pages left to the gov.pl lookup). Step 2c (our own database,
#19) is out of the pipeline for now (team decision). Any EUvsDisinfo source, whichever lookup
found it, is context only. The candidates go to step 3 (`rerank.rerank`, the linked page left out) and
steps 4 and 5 (`judge.judge`, verdict from `decide()`). When the evidence is not enough and time
remains, the web is searched once more with a rewritten query and the claim is judged again.

A source that fails adds a limitation; when every source failed, or the judge did not answer, the
claim is not checked, never "brak wystarczających dowodów". A claim that runs out of time is not
checked either, and keeps the limitations of the sources that had already failed. Every step's
time goes to the log; the reranker and judge calls are priced like the extraction call.
"""

import asyncio
import itertools
import logging
import os
import time

from pydantic import BaseModel
from pydantic_ai import ModelResponse, capture_run_messages
from pydantic_ai.messages import ModelMessage, ModelRequest

from prawdowid import (
    euvsdisinfo,
    factcheck,
    govpl,
    injection,
    judge,
    legal,
    rerank,
    websearch,
)
from prawdowid.contract import ModelCall, Source, Verdict

log = logging.getLogger("prawdowid")

# Hyperparameters, first guesses for the 30 s median, not tuned.
# Whole check, from the request to the last verdict (the API gives up at 60 s).
CHECK_BUDGET_S = float(os.getenv("PRAWDOWID_CHECK_BUDGET_S") or 25)
# The retry starts only with at least this much time left: a web search, rerank and judge again.
RETRY_MIN_S = float(os.getenv("PRAWDOWID_RETRY_MIN_S") or 18)
# EUvsDisinfo only adds context: it may not hold up the claim for its own 15 s deadline.
EUVSDISINFO_BUDGET_S = float(os.getenv("PRAWDOWID_EUVSDISINFO_BUDGET_S") or 5)

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
SOURCES_FAILED = (
    "Nie sprawdzono: żadne źródło nie zwróciło wyników ani nie odpowiedziało, "
    "więc nie wydajemy werdyktu."
)


class ClaimCheck(BaseModel):
    judgement: judge.Judgement
    # Reranker and judge calls; None when a request may be billed but its price is unknown.
    cost_usd: float | None
    steps_ms: dict[str, int]
    model_calls: list[ModelCall] = []


async def check_claim(
    claim: str,
    queries: list[str],
    deadline: float,
    exclude_url: str | None = None,
    govpl_queries: list[str] = (),
    legal_queries: list[str] = (),
    factcheck_queries: list[str] = (),
) -> ClaimCheck:
    """Verdict for one claim. `deadline` is `loop.time()` when the whole check must end.

    `queries` go to web search, `govpl_queries` to the gov.pl site search (to the web when it is
    switched off), `legal_queries` to the registers of law (nothing when empty),
    `factcheck_queries` to Google Fact Check next to the claim itself.
    """
    steps: dict[str, int] = {}
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
    laws = [q for q in legal_queries if q.strip()] if legal.ENABLED else []
    if _now() >= deadline:  # nothing is started after the budget ran out
        return _done(claim, _time_limit(found), runs, steps)
    try:
        async with asyncio.timeout_at(deadline):
            await _retrieve(
                claim, searched, gov, steps, found, laws, list(factcheck_queries)
            )
            candidates = _candidates(found)
            judgement = await _judge(claim, candidates, exclude_url, steps, runs)
    except TimeoutError:
        # The cost is None for a model request cut mid-flight, 0 when only search was cut.
        return _done(claim, _time_limit(found), runs, steps)
    # Injections the judge found in retrieved pages, kept from both passes.
    events = list(judgement.security_events)

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
                    more = candidates + _candidates({"web": [web]})
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
    if len(limits) == len(found) and not candidates:  # every source failed
        reason = TIME_LIMIT.format(budget=CHECK_BUDGET_S) if cut else SOURCES_FAILED
        judgement = _not_checked(reason)
    # The main reason first, then what each source said.
    reasons = judgement.limitations if judgement.verdict is Verdict.NOT_CHECKED else []
    judgement.limitations = list(
        dict.fromkeys([*reasons, *limits.values(), *judgement.limitations])
    )
    judgement.security_events = events[:1]  # same kind and location: one is enough
    return _done(claim, judgement, runs, steps)


async def _retrieve(
    claim: str,
    queries: list[str],
    gov: list[str] | None,
    steps: dict[str, int],
    found: dict,
    laws: list[str] = (),
    fc_queries: list[str] = (),
) -> None:
    """Steps 2a, EUvsDisinfo, gov.pl (when `gov` is set), law registers (when `laws` is set) and 2b at once, each answer stored in `found` as it arrives.

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

    async with asyncio.TaskGroup() as tg:
        # The prompt asks for 1 or 2 keyword queries; never more Fact Check calls than that.
        tg.create_task(
            keep("factcheck", lambda c: _search_claims([c, *fc_queries[:2]]))
        )
        tg.create_task(keep("euvsdisinfo", _search_cases))
        tg.create_task(_timed(steps, "web", all_web))
        if gov is not None:
            tg.create_task(keep("govpl", lambda _: _search_govpl(gov)))
        if laws:
            tg.create_task(keep("legal", lambda c: _search_legal(laws, c)))
        # Step 2c (`cache.search_documents`, #19) plugs in here when it is back in the pipeline.


def _candidates(found: dict) -> list[Source]:
    sources = [
        h.source
        for name in ("factcheck", "euvsdisinfo")
        if name in found
        for h in found[name].hits
    ]
    webs = [*found["web"], *(found[k] for k in ("govpl", "legal") if k in found)]
    sources += [d.to_source(fragment=d.text) for w in webs for d in w.documents]
    return [_context_only(s) for s in sources]


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
        "legal": found["legal"].limitation if "legal" in found else None,
        "web": web,
    }
    return {k: v for k, v in limits.items() if v}


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
        return websearch.WebSearch(limitation=websearch.SEARCH_UNAVAILABLE)


async def _search_govpl(queries: list[str]) -> websearch.WebSearch:
    try:
        return await govpl.search_govpl(queries)
    except Exception:
        log.exception("gov.pl search failed")
        return websearch.WebSearch(limitation=govpl.LOOKUP_UNAVAILABLE)


async def _search_legal(queries: list[str], claim: str) -> websearch.WebSearch:
    try:
        return await legal.search_legal(queries, claim)
    except Exception:
        log.exception("legal search failed")
        return websearch.WebSearch(limitation=legal.LOOKUP_UNAVAILABLE)


async def _search_claims(queries: list[str]) -> factcheck.FactCheckLookup:
    """Every query at once, reviews merged by URL taking turns between queries (the claim's own
    first) and capped at one page: keyword queries match broadly, and rerank keeps the first
    documents, so more reviews would push web, gov.pl and law sources out. Unavailable only when
    every lookup failed."""
    queries = list(dict.fromkeys(q.strip() for q in queries if q.strip()))
    lookups = await asyncio.gather(
        *map(factcheck.search_claims, queries), return_exceptions=True
    )
    for lookup in lookups:
        if isinstance(lookup, Exception):
            log.error("factcheck failed: %r", lookup)
    answered = [lookup.hits for lookup in lookups if not isinstance(lookup, Exception)]
    hits: dict[str, factcheck.FactCheckHit] = {}
    for turn in itertools.zip_longest(*answered):
        for h in turn:
            if h:
                hits.setdefault(str(h.source.url), h)
    if not hits and all(
        isinstance(lookup, Exception) or lookup.limitation for lookup in lookups
    ):
        return factcheck.FactCheckLookup(limitation=factcheck.LOOKUP_UNAVAILABLE)
    return factcheck.FactCheckLookup(hits=list(hits.values())[: factcheck.PAGE_SIZE])


async def _search_cases(claim: str) -> euvsdisinfo.EuvsdisinfoLookup:
    try:
        return await asyncio.wait_for(
            euvsdisinfo.search_cases(claim), EUVSDISINFO_BUDGET_S
        )
    except Exception:  # TimeoutError of its own budget included
        log.exception("euvsdisinfo failed")
        return euvsdisinfo.EuvsdisinfoLookup(limitation=euvsdisinfo.LOOKUP_UNAVAILABLE)


async def _judge(
    claim: str,
    candidates: list[Source],
    exclude_url: str | None,
    steps: dict[str, int],
    runs: list[list[ModelMessage]],
    prefix: str = "",
) -> judge.Judgement:
    """Steps 3 to 5. The linked page is never evidence for its own claims."""
    # Report-only screen of every retrieved page in code, next to the judge's own flag.
    # CPU-bound (tens of ms per long page), so off the event loop; timed like the other steps.
    events = await _timed(
        steps,
        prefix + "screen",
        asyncio.to_thread,
        injection.screen_sources,
        candidates,
        exclude_url,
    )
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
                ),
                "security_events": events,
            }
        )
    judgement.security_events = [*events, *judgement.security_events]
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
