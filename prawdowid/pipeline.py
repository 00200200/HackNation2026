"""Steps 2 to 5 for one claim, under the time budget of the whole check.

Step 2 runs three lookups at once: 2a Google Fact Check (`factcheck.search_claims`), EUvsDisinfo
known narratives (`euvsdisinfo.search_cases`, context that never decides alone) and 2b web search
and fetch (`websearch.search_web`, one search per query of the claim). Step 2c (our own database,
#19) is out of the pipeline for now (team decision). The candidates go to step 3 (`rerank.rerank`, the linked page left out) and
steps 4 and 5 (`judge.judge`, verdict from `decide()`). When the evidence is not enough and time
remains, the web is searched once more with a rewritten query and the claim is judged again.

A source that fails adds a limitation; when every source failed, the claim is not checked, never
"brak wystarczających dowodów". A claim that runs out of time is not checked either. Every step's
time goes to the log; the reranker and judge calls are priced like the extraction call.
"""

import asyncio
import logging
import os
import time

from pydantic import BaseModel
from pydantic_ai import ModelResponse, capture_run_messages
from pydantic_ai.messages import ModelMessage, ModelRequest

from prawdowid import euvsdisinfo, factcheck, judge, rerank, websearch
from prawdowid.contract import ModelCall, SecurityEvent, Source, Verdict

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
    claim: str, queries: list[str], deadline: float, exclude_url: str | None = None
) -> ClaimCheck:
    """Verdict for one claim. `deadline` is `loop.time()` when the whole check must end."""
    steps: dict[str, int] = {}
    # Messages of each reranker and judge run, priced and logged in `_done`.
    runs: list[list[ModelMessage]] = []
    # Injections the judge found in retrieved pages, kept from both passes.
    events: list[SecurityEvent] = []
    try:
        async with asyncio.timeout_at(deadline):
            candidates, limits = await _retrieve(claim, queries, steps)
            judgement = await _judge(claim, candidates, exclude_url, steps, runs)
            events += judgement.security_events
    except TimeoutError:
        # The cost is None for a model request cut mid-flight, 0 when only search was cut.
        return _done(
            claim, _not_checked(TIME_LIMIT.format(budget=CHECK_BUDGET_S)), runs, steps
        )

    # With no queries the first pass already searched the claim itself.
    retry = queries and claim not in queries
    cut = False
    if retry and _needs_more(judgement) and deadline - _now() >= RETRY_MIN_S:
        try:
            async with asyncio.timeout_at(deadline):
                # ponytail: the claim itself is the rewritten query (the first pass used the
                # model's queries); a HyDE-FC rewrite costs one more model call per claim.
                web = await _timed(steps, "retry_web", _search_web(claim))
                if web.documents:
                    more = candidates + [
                        d.to_source(fragment=d.text) for d in web.documents
                    ]
                    judgement = await _judge(
                        claim, more, exclude_url, steps, runs, "retry_"
                    )
                    events += judgement.security_events
                    # Only a finished retry counts: a cut one keeps the first pass as it was.
                    candidates = more
                    limits.pop("web", None)
        except TimeoutError:
            log.info("retry cut by the time limit claim=%r", claim)
            cut = True

    if len(limits) == 3 and not candidates:  # every source failed
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
    claim: str, queries: list[str], steps: dict[str, int]
) -> tuple[list[Source], dict[str, str]]:
    """Steps 2a, EUvsDisinfo and 2b at once: candidates and the limitation of each failed
    source."""
    lookup, cases, webs = await asyncio.gather(
        _timed(steps, "factcheck", _search_claims(claim)),
        _timed(steps, "euvsdisinfo", _search_cases(claim)),
        _timed(
            steps,
            "web",
            asyncio.gather(*(_search_web(q) for q in queries or [claim])),
        ),
        # Step 2c (`cache.search_documents`, #19) plugs in here when it is back in the pipeline.
    )
    documents = [d for w in webs for d in w.documents]
    candidates = (
        [h.source for h in lookup.hits]
        + [h.source for h in cases.hits]
        + [d.to_source(fragment=d.text) for d in documents]
    )
    web_limit = None if documents else next((w.limitation for w in webs), None)
    limits = {
        "factcheck": lookup.limitation,
        "euvsdisinfo": cases.limitation,
        "web": web_limit,
    }
    return candidates, {k: v for k, v in limits.items() if v}


async def _search_web(query: str) -> websearch.WebSearch:
    """An unexpected error (cache write, extraction) is a limitation of this source only."""
    try:
        # Bounded inside: search by SEARCH_BUDGET_S, each page by PAGE_BUDGET_S.
        return await websearch.search_web(query)
    except Exception:
        log.exception("web search failed query=%r", query)
        return websearch.WebSearch(limitation=websearch.SEARCH_UNAVAILABLE)


async def _search_claims(claim: str) -> factcheck.FactCheckLookup:
    try:
        return await factcheck.search_claims(claim)
    except Exception:
        log.exception("factcheck failed")
        return factcheck.FactCheckLookup(limitation=factcheck.LOOKUP_UNAVAILABLE)


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
    ranking = await _priced(
        runs,
        _timed(
            steps,
            prefix + "rerank",
            rerank.rerank(claim, candidates, exclude_url=exclude_url),
        ),
    )
    return await _priced(
        runs, _timed(steps, prefix + "judge", judge.judge(claim, ranking))
    )


async def _priced(runs: list[list[ModelMessage]], aw):
    """Keeps the messages of the model run inside `aw` in `runs`, also when the time limit cuts
    it: a request without an answer may be billed, so its price is unknown (None)."""
    with capture_run_messages() as messages:
        try:
            return await aw
        finally:
            runs.append(messages)


def _needs_more(judgement: judge.Judgement) -> bool:
    """Not enough evidence, and not because sources disagree or the judge failed."""
    return judgement.verdict is Verdict.INSUFFICIENT_EVIDENCE and not (
        {judge.CONFLICT, judge.JUDGE_UNAVAILABLE} & set(judgement.limitations)
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


async def _timed(steps: dict[str, int], name: str, aw):
    started = time.perf_counter()
    try:
        return await aw
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
