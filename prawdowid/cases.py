"""Moderator cases (brief section 2, scenario H): the questions a person should look at, grouped.

A check adds a report to the moderator's queue when a checked claim ends `brak wystarczających
dowodów`, when the check logged a security event, or when a claim on a high-risk topic
(`HIGH_RISK`) ended false, misleading or without enough evidence. The report joins the open case
holding the same claim once normalised (`key`) or a similar one: their words, cut to stems as the
corpus search cuts them (`corpus_bm25.terms`), overlap by at least `MIN_SIMILARITY` (Jaccard).
Otherwise it opens a case with the next number. `report` returns the case only after the file was
written; when the write fails it logs that and returns None, so an answer never says a question
went to the moderator when it did not (brief section 5: a recommended hand-off is not a hand-off).

Who reads the queue: whoever the administrator gives `PRAWDOWID_ADMIN_TOKEN` (a moderator or an
analyst), through `GET /api/cases` (`read_cases`). Nobody is notified otherwise: no e-mail, no webhook.

Storage: one JSON line per case in `PRAWDOWID_CASES` (default `cases.jsonl` next to the check log,
so on the `checklog` volume in Docker) with its reports: session, time, channel, reasons, the
masked claims (the masked question when there is no claim), the masked page URL, the lookups that
ran and the URLs they found. A report older than `RETENTION_DAYS` is dropped on every write, a case
left without reports goes with it, and `delete_session` removes one session's reports. The last
case number is kept in a `.seq` file next to it, so a number is never given twice. Writers hold a
file lock, as in the check log.
"""

import fcntl
import logging
import os
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from prawdowid import checklog, corpus_bm25
from prawdowid.contract import CheckResult, ClaimResult, ModeratorCase, Verdict
from prawdowid.privacy import RETENTION_DAYS, mask_personal_data

log = logging.getLogger("prawdowid")

CASES = Path(
    os.getenv("PRAWDOWID_CASES") or checklog.CHECK_LOG.with_name("cases.jsonl")
)
# Share of their distinct stems two claims must have in common to be one case: a first guess, not
# tuned. On hand-made rumours (none from the eval set), rewordings score 0.5 to 0.86 and unrelated
# claims 0.0. Shared words are not shared meaning: "Rząd podniósł podatki" and "Rząd obniżył
# podatki" (0.5) land in one case too, and the moderator sees every claim of a case.
MIN_SIMILARITY = float(os.getenv("PRAWDOWID_CASE_MIN_SIMILARITY") or 0.5)
# A check without claims (an unclear text, a refused link) keeps at most this much of the question.
QUESTION_CHARS = 300
# Step names of the lookups in `pipeline.check_claim`: what a report lists as the sources tried.
LOOKUPS = frozenset({"factcheck", "euvsdisinfo", "govpl", "web", "corpus"})
# Topics where a claim the sources did not confirm can hurt people at once ("sprawy wysokiego
# ryzyka"), matched on the folded claim (lower case, no diacritics). A short list chosen by hand and
# not tuned on any case; which topics the administrator wants is UNCONFIRMED.
HIGH_RISK = {
    "alert": re.compile(
        r"\bewakuac|\brcb\b|\bschron(?:u|ie|em|y|ow|ach|ami)?\b|\bsyren\w* alarm"
        r"|\balarm\w* (?:powietrzn|bombow)|\bstan\w* wyjatkow"
    ),
    "health": re.compile(
        r"\bepidemi|\bpandemi|\bskazon\w* wod|\bskazeni\w* wod|\bniezdatn\w* do picia"
    ),
    "elections": re.compile(
        r"\bwybor(?:y|ow|ach|ami|om)\b|\bwyborcz|\bglosowani|\breferend|\bpkw\b"
    ),
    "mobilisation": re.compile(
        r"\bmobilizac|\bpobor\w* do (?:wojska|armii)|\bkwalifikacj\w* wojskow|\bstan\w* wojenn"
    ),
}
# A claim on a high-risk topic goes to the moderator unless the sources confirmed it.
UNCONFIRMED = frozenset(
    {Verdict.FALSE, Verdict.MISLEADING, Verdict.INSUFFICIENT_EVIDENCE}
)


class Report(BaseModel):
    """One question in a case, as stored."""

    session: str
    time: AwareDatetime
    channel: str
    # "insufficient_evidence", "high_risk:<topic>", "security_event:<location>".
    reasons: list[str]
    claims: list[str] = Field(min_length=1)
    page: str | None = None
    lookups: list[str] = []
    sources: list[str] = []


class Case(BaseModel):
    id: int
    opened_at: AwareDatetime
    reports: list[Report]


class CaseSummary(BaseModel):
    """A case as the moderator reads it (`GET /api/cases`): no session ids."""

    id: int
    opened_at: datetime
    last_seen: datetime
    count: int
    reasons: list[str]
    claims: list[str]
    channels: dict[str, int]
    pages: list[str]
    lookups: list[str]
    sources: list[str]


def key(text: str) -> str:
    """The claim normalised: folded and cut to its words, so letter case, diacritics, punctuation
    and spacing never tell two claims apart."""
    return " ".join(re.findall(r"\w+", corpus_bm25.fold(text)))


def similarity(a: str, b: str) -> float:
    """1.0 for the same normalised claim, else the Jaccard overlap of their stems."""
    if key(a) == key(b):
        return 1.0
    x, y = set(corpus_bm25.terms(a)), set(corpus_bm25.terms(b))
    return len(x & y) / len(x | y) if x and y else 0.0


def high_risk(text: str) -> list[str]:
    """The `HIGH_RISK` topics the text is about."""
    folded = corpus_bm25.fold(text)
    return [topic for topic, pattern in HIGH_RISK.items() if pattern.search(folded)]


def report(
    session: str,
    channel: str,
    question: str,
    result: CheckResult,
    *,
    started_at: datetime,
) -> ModeratorCase | None:
    """Adds the check to the moderator's queue when it needs a person. The case it joined, or
    None: nothing to report, the session was deleted while the check ran, or the write failed."""
    entry = _report(session, channel, question, result)
    deleted = checklog.DELETED.get(session)
    if entry is None or (deleted and started_at <= deleted):
        return None
    try:
        return _locked(_add, entry)
    # Any failure: the answer must neither fail nor name a case that was not stored.
    except Exception:
        log.exception("moderator case not stored")
        return None


def read_cases() -> list[CaseSummary]:
    """Open cases, the most reported first, then the latest. Writers swap the file atomically, so
    no lock."""
    rows = [_summary(c) for c in _load(CASES)]
    return sorted(rows, key=lambda r: (r.count, r.last_seen), reverse=True)


def delete_session(session: str) -> int:
    """Removes every report of the session; a case left without reports goes too. Number removed."""
    return _locked(_drop_session, session)


def _reasons(claim: ClaimResult) -> list[str]:
    reasons = []
    if claim.verdict is Verdict.INSUFFICIENT_EVIDENCE:
        reasons.append("insufficient_evidence")
    if claim.verdict in UNCONFIRMED:
        reasons += [f"high_risk:{topic}" for topic in high_risk(claim.claim)]
    return reasons


def _report(
    session: str, channel: str, question: str, result: CheckResult
) -> Report | None:
    """The report this check adds, or None when it needs no person."""
    found = [(c, _reasons(c)) for c in result.claims]
    flagged = [c for c, why in found if why]
    reasons = {r for _, why in found for r in why}
    reasons |= {f"security_event:{e.location}" for e in result.security_events}
    if not reasons:
        return None
    # The claims that need a person; for a security event alone every claim, else the question.
    subjects = flagged or result.claims
    claims = [mask_personal_data(c.claim) for c in subjects]
    steps = {s.removeprefix("retry_") for c in subjects for s in c.steps_ms}
    return Report(
        session=session,
        time=datetime.now(UTC),
        channel=channel,
        reasons=sorted(reasons),
        claims=claims or [mask_personal_data(question)[:QUESTION_CHARS]],
        page=result.page and mask_personal_data(result.page.url),
        lookups=sorted(steps & LOOKUPS),
        sources=sorted(
            {mask_personal_data(str(s.url)) for c in subjects for s in c.sources}
        ),
    )


def _add(path: Path, entry: Report) -> ModeratorCase:
    # ponytail: compares with every stored claim and rewrites the file on each report, like the
    # check log; fine for a demo queue.
    cases = _load(path)
    score, case = max(
        ((_score(entry, c), c) for c in cases),
        default=(0.0, None),
        key=lambda pair: pair[0],
    )
    status = "updated"
    if case is None or score < MIN_SIMILARITY:
        case = Case(id=_next_id(path, cases), opened_at=entry.time, reports=[])
        cases.append(case)
        status = "created"
    case.reports.append(entry)
    _save(path, cases)
    return ModeratorCase(id=case.id, status=status, count=len(case.reports))


def _score(entry: Report, case: Case) -> float:
    """How close the closest pair of claims is, one from the report and one from the case."""
    return max(
        similarity(new, old)
        for new in entry.claims
        for r in case.reports
        for old in r.claims
    )


def _next_id(path: Path, cases: list[Case]) -> int:
    """One more than any number given before (the `.seq` file) or still open."""
    seq = path.with_suffix(".seq")
    try:
        last = int(seq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = 0
    number = max([last, *(c.id for c in cases)]) + 1
    seq.write_text(str(number), encoding="utf-8")
    return number


def _drop_session(path: Path, session: str) -> int:
    cases = _load(path)
    kept = [
        c.model_copy(update={"reports": [r for r in c.reports if r.session != session]})
        for c in cases
    ]
    removed = sum(len(c.reports) for c in cases) - sum(len(c.reports) for c in kept)
    if removed:
        _save(path, [c for c in kept if c.reports])
    return removed


def _summary(case: Case) -> CaseSummary:
    reports = case.reports
    return CaseSummary(
        id=case.id,
        opened_at=case.opened_at,
        last_seen=max(r.time for r in reports),
        count=len(reports),
        reasons=sorted({x for r in reports for x in r.reasons}),
        claims=list(dict.fromkeys(c for r in reports for c in r.claims)),
        channels=dict(Counter(r.channel for r in reports)),
        pages=sorted({r.page for r in reports if r.page}),
        lookups=sorted({x for r in reports for x in r.lookups}),
        sources=sorted({x for r in reports for x in r.sources}),
    )


def _load(path: Path) -> list[Case]:
    """Cases within retention: expired reports dropped, then cases without reports. A damaged line
    is skipped, and gone after the next write."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    cases = []
    for line in lines:
        try:
            case = Case.model_validate_json(line)
        except ValidationError:
            continue
        case.reports = [r for r in case.reports if r.time > cutoff]
        if case.reports:
            cases.append(case)
    return cases


def _save(path: Path, cases: list[Case]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(c.model_dump_json() + "\n" for c in cases), encoding="utf-8")
    tmp.replace(path)


def _locked(fn, *args):
    """`fn(path, *args)` holding the store's lock, across threads and processes (as in the check
    log: flock locks per descriptor, so each call opens its own)."""
    path = CASES  # looked up per call, so tests can point it elsewhere
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return fn(path, *args)
