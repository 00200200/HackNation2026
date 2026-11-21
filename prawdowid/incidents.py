"""Scenario I: match the input against the organiser's incident base.

A match is shown as neutral context next to the claims. It never sets or changes a verdict.

The organiser has not shared the base yet, so the shipped file is empty and nothing matches.
File format, UNCONFIRMED until we see the organiser's file: a JSON list of objects, or a CSV with
a header row, with these fields:
- id (required): the incident's id in the organiser's base.
- text (required): the false narrative or claim, as the base describes it.
- url (optional): the address where the incident was seen; matched exactly (canonical form).
- domain (optional): a domain flagged in the base; any link on it matches. Not taken from url,
  so one incident on a big platform does not flag every link to that platform.
"""

import csv
import json
import logging
import os
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError

from prawdowid.contract import IncidentMatch, MatchKind
from prawdowid.rerank import canonical_url

log = logging.getLogger("prawdowid")

INCIDENTS_PATH = os.getenv("PRAWDOWID_INCIDENTS_PATH") or str(
    Path(__file__).parent / "data" / "incidents.json"
)
# Hyperparameters, first guesses, not tuned: no real incidents to tune on yet.
MIN_SIMILARITY = float(os.getenv("PRAWDOWID_INCIDENT_MIN_SIMILARITY") or 0.7)
MAX_MATCHES = int(os.getenv("PRAWDOWID_INCIDENT_MAX_MATCHES") or 3)

URL_IN_TEXT = re.compile(r"https?://[^\s<>\"']+")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class Incident(BaseModel):
    # Organisers' exports often have numeric ids.
    model_config = ConfigDict(coerce_numbers_to_str=True)

    id: str
    text: str
    url: str | None = None
    domain: str | None = None


@lru_cache
def load_incidents(path: str = INCIDENTS_PATH) -> tuple[Incident, ...]:
    """The base from a .json or .csv file. A missing or broken file is an empty base, a bad row
    is skipped; both are logged."""
    file = Path(path)
    if not file.exists():
        log.info("incident base not found path=%s, matching nothing", path)
        return ()
    try:
        # utf-8-sig: spreadsheet CSV exports often start with a BOM.
        with file.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f)) if file.suffix == ".csv" else json.load(f)
    except (OSError, ValueError) as exc:
        log.warning("incident base unreadable path=%s error=%r", path, exc)
        return ()
    if not isinstance(rows, list):
        log.warning("incident base is not a list path=%s", path)
        return ()
    incidents = []
    for n, row in enumerate(rows):
        try:
            # Empty CSV cells mean "not given".
            incidents.append(
                Incident(
                    **{
                        k: v
                        for k, v in row.items()
                        if k is not None and v not in ("", None)
                    }
                )
            )
        except (AttributeError, TypeError, ValidationError) as exc:
            log.warning("incident row skipped path=%s row=%d error=%r", path, n, exc)
    return tuple(incidents)


def match_incidents(
    text: str, incidents: tuple[Incident, ...] | None = None
) -> list[IncidentMatch]:
    """Incidents the input looks like, strongest first: same URL, flagged domain, similar text."""
    incidents = load_incidents() if incidents is None else incidents
    if not incidents:
        return []
    urls = {_canonical(u.rstrip(".,;:!?)")) for u in URL_IN_TEXT.findall(text)}
    urls.discard("")  # rejected URLs
    hosts = {_host(u) for u in urls} - {""}
    pieces = [_norm(p) for p in [text, *SENTENCE_END.split(text)]]
    matches = []
    for incident in incidents:
        match = _match(incident, urls, hosts, [p for p in pieces if p])
        if match:
            matches.append(match)
    order = list(MatchKind)
    matches.sort(key=lambda m: (order.index(m.matched_on), -(m.similarity or 0)))
    return matches[:MAX_MATCHES]


def _match(
    incident: Incident, urls: set[str], hosts: set[str], pieces: list[str]
) -> IncidentMatch | None:
    found = {"incident_id": incident.id, "incident_text": incident.text}
    if incident.url and _canonical(incident.url) in urls:
        return IncidentMatch(**found, matched_on=MatchKind.URL, url=incident.url)
    domain = _host(incident.domain or "")
    if domain and any(h == domain or h.endswith("." + domain) for h in hosts):
        return IncidentMatch(**found, matched_on=MatchKind.DOMAIN, url=incident.url)
    target = _norm(incident.text)
    # ponytail: difflib over every incident and sentence, O(n·m); fine for a base of hundreds.
    score = max((SequenceMatcher(None, p, target).ratio() for p in pieces), default=0)
    if target and score >= MIN_SIMILARITY:
        return IncidentMatch(
            **found,
            matched_on=MatchKind.TEXT,
            url=incident.url,
            similarity=round(score, 2),
        )
    return None


def _canonical(url: str) -> str:
    # A URL urlsplit rejects (e.g. "http://[x") is no URL: it must not fail the check.
    try:
        return canonical_url(url)
    except ValueError:
        return ""


def _host(value: str) -> str:
    """Host without www., from a URL or a bare domain ("propaganda.example/")."""
    try:
        host = urlsplit(value if "//" in value else "//" + value).hostname or ""
    except ValueError:
        return ""
    return host.removeprefix("www.")


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())
