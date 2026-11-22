"""Short justification of a claim's verdict, written in code from the evidence that decided it.

Never from a model's note: the extraction model's `reason` says why a claim is checkable, which
tells a citizen nothing about the verdict. Here every sentence names a publisher, a date and the
verified quote of a source the verdict rests on.
"""

from collections.abc import Iterable

from prawdowid.contract import Source, Verdict

QUOTE_CHARS = 160
MAX_CITED = 2

NOT_CHECKED = (
    "To nie jest ocena twierdzenia. Nie mogliśmy go teraz sprawdzić (brak odpowiedzi "
    "źródeł albo limit czasu), więc nie wiemy, czy jest prawdziwe. Spróbuj ponownie za chwilę."
)
NOT_VERIFIABLE = (
    "To twierdzenie nie opisuje faktu, który da się porównać ze źródłami "
    "(na przykład jest opinią, oceną albo prognozą), więc nie wydajemy oceny."
)
NO_SOURCES = "Nie znaleźliśmy źródeł, które potwierdzałyby albo obalały to twierdzenie."
CONFLICT = (
    "Wiarygodne źródła mówią co innego: potwierdza {supports}, przeczy {refutes}. "
    "Nie rozstrzygamy, które ma rację."
)
DATA_GAP = "Źródła mówią, że dostępne dane nie pozwalają tego sprawdzić: {cited}."
TOO_FEW = "Znaleźliśmy za mało, żeby to rozstrzygnąć: {cited}."
CONTEXT = "Twierdzenie pomija ważny kontekst: {context} ({cited})."
SEE_SOURCES = "Ocena wynika ze źródeł wymienionych poniżej."
SUPPORTED = "Potwierdza to: {cited}."
REFUTED = "Przeczy temu: {cited}."


def explain(
    verdict: Verdict,
    stances: Iterable[tuple[Source, str, str | None]],
    conflict: bool = False,
) -> str:
    """One or two sentences for the verdict.

    `stances` is the verified evidence the verdict rests on, as (source, stance, missing context),
    the stance being "supports", "refutes", "context", "gap" or "weak" (too little to decide).
    The caller filters it with the verdict rules; `conflict` says they found two sides.
    """
    items = list(stances)
    by = {
        stance: [s for s, st, _ in items if st == stance]
        for stance in ("supports", "refutes", "context", "gap", "weak")
    }
    match verdict:
        case Verdict.NOT_CHECKED:
            return NOT_CHECKED
        case Verdict.NOT_VERIFIABLE:
            return NOT_VERIFIABLE
        case Verdict.CONFIRMED if by["supports"]:
            return SUPPORTED.format(cited=_cite(by["supports"]))
        case Verdict.FALSE if by["refutes"]:
            return REFUTED.format(cited=_cite(by["refutes"]))
        case Verdict.CONFIRMED | Verdict.FALSE:
            return SEE_SOURCES
        case Verdict.MISLEADING:
            return _misleading(items)
    if conflict and by["supports"] and by["refutes"]:
        return CONFLICT.format(
            supports=_cite(by["supports"]), refutes=_cite(by["refutes"])
        )
    if by["gap"]:
        return DATA_GAP.format(cited=_cite(by["gap"], False))
    if items:
        return TOO_FEW.format(cited=_cite([s for s, _, _ in items]))
    return NO_SOURCES


def _misleading(items: list[tuple[Source, str, str | None]]) -> str:
    # The rules need a missing context found in a source, so `grounded` is never empty there.
    grounded = [(s, ctx) for s, _, ctx in items if ctx]
    if not grounded:
        return SEE_SOURCES
    source, context = grounded[0]
    return CONTEXT.format(context=context.rstrip(". "), cited=_cite([source]))


def _cite(sources: list[Source], quote: bool = True) -> str:
    """ "MON, komunikat z 3.07.2026: „…”" for up to MAX_CITED distinct documents."""
    seen: dict[str, Source] = {}
    for s in sources:
        seen.setdefault(str(s.url), s)
    cited = list(seen.values())[:MAX_CITED]
    parts = [_one(s, quote) for s in cited]
    extra = len(seen) - len(cited)
    text = "; ".join(parts)
    return text + (f"; i jeszcze {extra}" if extra > 0 else "")


def _one(s: Source, quote: bool) -> str:
    who = s.publisher or str(s.url.host)
    when = f", {_date(s)}" if s.published_at else ", bez daty"
    text = f"{who}{when}"
    if s.snippet_only:
        text += ", fragment z wyników wyszukiwarki"
    if quote and s.fragment:
        text += f": „{_short(s.fragment)}”"
    return text


def _date(s: Source) -> str:
    d = s.published_at
    return f"{d.day}.{d.month:02d}.{d.year}"


def _short(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= QUOTE_CHARS:
        return text
    return text[:QUOTE_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
