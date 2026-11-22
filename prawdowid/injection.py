"""Prompt-injection pre-checks in code, independent of the models they protect.

`screen` runs on the user's input and the linked page. `screen_sources` runs on every retrieved
evidence page before rerank and judge, report-only: a flagged page is kept, so a fact-check that
quotes a scam message never loses its evidence.
"""

import logging
import re

from stackone_defender import PromptDefense

from prawdowid.contract import SecurityEvent, Source
from prawdowid.rerank import canonical_url

log = logging.getLogger("prawdowid")

# Deterministic pre-check, independent of the model it protects. No maintained offline detector
# covers Polish (llm-guard's DeBERTa is English-only; Prompt Guard 2 was not evaluated on Polish).
# Singular imperatives only: "zignorował", "ignorujemy" or a plural "zignorujcie" in reported
# speech are about people, not the model.
# ponytail: a fixed phrase list misses paraphrases and other languages and flags a quoted
# singular command; the model flag covers part of that. Add a screening model if the eval
# shows misses.
INJECTION_PATTERNS = re.compile(
    r"""
    # Override of earlier rules: singular imperative or "proszę" + infinitive, with or without
    # Polish letters.
    (\b(zignoruj|ignoruj|pomi[nń])|\bprosz[eę]\s+(zignorowa[cć]|pomin[aą][cć]))\s+
        ((wszystk|wszelk|każd|kazd|moj|swoj|twoj|t[eąa]\b|dotychczasow|poprzedn|wcze[sś]niejsz
          |powy[zż]sz|systemow|otrzyman)\w*\s+)*
        (instrukcj|polece|zasad|reguł|regul|wytyczn|prompt)
    | \b(zignoruj|ignoruj|pomi[nń])\s+(wszystko\s+)?powy[zż]sz\w*
    | \bzapomnij\s+o\s+(\w+\s+){0,2}(instrukcj|polece|prompt)
    | \b(ignore|disregard|forget)\s+(all\s+|any\s+)?(of\s+)?(the\s+)?
        ((previous|prior|earlier|your|my|system)\s+)+(instructions?|rules|prompts?|directions|commands)\b
    | \b(ignore|disregard)\s+(all\s+|everything\s+)?(of\s+)?(the\s+)?above\b
    # A new role or a fake system turn.
    | \bod\s+teraz\s+jeste[sś]\b | \[\s*system\s*\]
    | \byou\s+are\s+now\s+(an?\s+)?(ai|assistant|bot|model|unrestricted|dan)\b
    # Text addressed to the model itself.
    | \b(note|message)\s+to\s+the\s+(ai|model|assistant)\b
    | \b(notatka|wiadomo[sś][cć]|polecenie)\s+dla\s+(ai|modelu|asystenta)\s*:
    # Asking for a verdict, a fixed answer or the prompt.
    | \b(oceń|oznacz)\s+(to|je|go|ją|wszystko)\s+jako\s+(prawd|potwierdz)
    | \b(mark|rate)\s+(this|it|everything)\s+as\s+(true|confirmed)
    | \bodpowiedz\s+(tylko|wyłącznie|jedynie)\b | \boutput\s+only\s+(the|one|a)\b
    | \b(ujawnij|pokaż|wypisz)\s+(mi\s+)?(swój\s+|swoje\s+|twój\s+|twoje\s+)?(prompt|instrukcj)
    | \b(reveal|print|show)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def screen(text: str, location: str = "input") -> list[SecurityEvent]:
    """Pattern pre-check for instructions aimed at the model, in user input or a fetched page."""
    if not INJECTION_PATTERNS.search(text):
        return []
    log.warning(
        "security_event kind=prompt_injection location=%s detector=patterns", location
    )
    return [SecurityEvent(location=location, detector="patterns")]


# StackOne Defender, the engine behind pydantic-ai-harness's PromptInjectionDefender, called
# directly: our pages never pass through an agent tool call, where that capability runs. Pattern
# tier only, as a second phrase list (mostly English) next to ours. Its ML tier rated a clean
# Polish page high risk (0.76, the same as Polish injections) when probed on 2026-11-22.
_defense = PromptDefense(block_high_risk=True, enable_tier2=False)
# Rules that fire on ordinary page text, not on instructions, so a verdict counts only with
# another detection. Character-level: gov.pl pages carry a Ukrainian/Russian menu next to Latin
# text, which `confusable_homoglyphs` reads as a disguise (live, 2026-11-22), and scraped HTML
# keeps zero-width and control characters. Single descriptive words: "RT is the only uncensored
# source" or "without restrictions" is how EUvsDisinfo and news describe a narrative.
_NOT_INSTRUCTIONS = {
    "confusable_homoglyphs",
    "invisible_unicode",
    "text_direction_override",
    "ansi_escape_sequence",
    "c0_control_character",
    "uncensored",
    "no_restrictions",
}


def _defender_flags(text: str) -> bool:
    verdict = _defense.defend_tool_result({"content": text}, "fetch_page")
    return not verdict.allowed and bool(set(verdict.detections) - _NOT_INSTRUCTIONS)


def screen_sources(
    sources: list[Source], exclude_url: str | None = None
) -> list[SecurityEvent]:
    """One `source` event when any retrieved page carries instructions aimed at the model. The
    linked page (`exclude_url`) is never evidence, and its own screen reports it as "page"."""
    excluded = canonical_url(exclude_url) if exclude_url else None
    for s in sources:
        if excluded and canonical_url(str(s.url)) == excluded:
            continue
        text = f"{s.title}\n{s.fragment or ''}"
        if INJECTION_PATTERNS.search(text):
            detector = "patterns"
        elif _defender_flags(text):
            detector = "defender"
        else:
            continue
        log.warning(
            "security_event kind=prompt_injection location=source detector=%s url=%s",
            detector,
            s.url,
        )
        return [SecurityEvent(location="source", detector=detector)]
    return []
