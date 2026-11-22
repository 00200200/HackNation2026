"""Exports for analysts: one answer as a STIX 2.1 bundle, and the check log as CSV or JSON.

STIX: built with the OASIS `stix2` library (3.0.2, checked 2026-11-22: `Identity`, `Report`, `Note`,
`ExternalReference`, `Bundle`). The bundle holds
- an Identity for faktczyfejk.pl (identity_class "system"), the author of everything else;
- a Report for the check (`object_refs` is required in STIX and the Report is what the notes are about);
- one Note per claim, labelled `verdict:<code>`: the claim as `abstract`, the verdict, the
  justification, the limitations and the sources' roles as `content`, the sources as
  `external_references` (url, publisher and date as description). A Note rather than an Opinion:
  an Opinion has only a five-step agree/disagree scale, which cannot say "not checked" or "not
  verifiable";
- when incidents from the organiser's base matched, one more Note with their ids as
  `external_references` (context only, as in the answer).
DISARM technique ids are never added: no source we read names one. Everything is built from the
answer the client already holds and masked again (prawdowid/privacy.py); nothing is fetched.
The import into OpenCTI is UNTESTED: the bundle parses back with `stix2.parse` and follows the
spec, no OpenCTI instance was available.

Check log export: a fixed list of fields of the masked record, without the session id (it links one
visitor's checks). Records outside retention are never in the file (`checklog.read_range`).
"""

import csv
import io
import uuid
from datetime import UTC, date, datetime, time, timedelta

import stix2

from prawdowid import checklog
from prawdowid.contract import CheckResult, ClaimResult, Source, Status
from prawdowid.privacy import RETENTION_DAYS
from prawdowid.privacy import mask_personal_data as mask

# The API reads at most this much of an export request (nginx cuts requests at 64k too).
MAX_ANSWER_BYTES = 64_000
# Rows of one check log export.
MAX_ROWS = 10_000
IDENTITY_NAME = "faktczyfejk.pl"
IDENTITY_URL = "https://faktczyfejk.pl"
CONTEXT_TYPES = {
    "disinfo_database"
}  # EUvsDisinfo: context, never evidence (pipeline.py)


def _reference(s: Source) -> stix2.ExternalReference:
    detail = ", ".join(
        x for x in (s.publisher, s.published_at and s.published_at.isoformat()) if x
    )
    if s.rating:
        detail += f" (ocena: {s.rating})"
    return stix2.ExternalReference(
        source_name=mask(s.publisher or s.title) or "source",
        url=mask(str(s.url)),
        description=mask(f"{s.title}. {detail}" if detail else s.title),
    )


def _content(c: ClaimResult) -> str:
    lines = [f"Ocena: {c.verdict.label}.", c.reasoning]
    context = [s for s in c.sources if s.source_type in CONTEXT_TYPES]
    if context:
        lines.append(
            "Kontekst, nie dowód: " + ", ".join(str(s.url) for s in context) + "."
        )
    lines += c.limitations
    return mask("\n".join(x for x in lines if x))


def stix_bundle(answer: CheckResult) -> str:
    """The answer as a serialised STIX 2.1 bundle. Raises ValueError when there is nothing to export."""
    if answer.status is not Status.OK or not answer.claims:
        raise ValueError("only an answer with checked claims can be exported")
    now = datetime.now(UTC)
    identity = stix2.Identity(
        name=IDENTITY_NAME,
        identity_class="system",
        description="Automated fact-checking service for Polish-language claims.",
        external_references=[
            stix2.ExternalReference(source_name=IDENTITY_NAME, url=IDENTITY_URL)
        ],
    )
    # The notes point at the report and the report lists them: its id is fixed first.
    report_id = f"report--{uuid.uuid4()}"
    notes = [
        stix2.Note(
            created_by_ref=identity.id,
            authors=[IDENTITY_NAME],
            abstract=mask(c.claim),
            content=_content(c),
            labels=[f"verdict:{c.verdict.value}"],
            external_references=[_reference(s) for s in c.sources] or None,
            object_refs=[report_id],
        )
        for c in answer.claims
    ]
    if answer.incident_matches:
        notes.append(
            stix2.Note(
                created_by_ref=identity.id,
                abstract="Matches with the organiser's incident base",
                content="Context only: a match never changes a verdict.",
                object_refs=[report_id],
                external_references=[
                    stix2.ExternalReference(
                        source_name="Incident base",
                        external_id=m.incident_id,
                        url=mask(m.url) if m.url else None,
                        description=mask(
                            f"{m.incident_text} (matched on {m.matched_on.value})"
                        ),
                    )
                    for m in answer.incident_matches
                ],
            )
        )
    report = stix2.Report(
        id=report_id,
        created_by_ref=identity.id,
        name="Fact check " + now.strftime("%Y-%m-%d %H:%M UTC"),
        published=now,
        report_types=["threat-report"],
        object_refs=[identity.id, *(n.id for n in notes)],
    )
    return stix2.Bundle(identity, report, *notes).serialize(pretty=True)


# Fields of a check log record that leave the service. `session` is left out on purpose.
LOG_FIELDS = (
    "time",
    "started_at",
    "latency_ms",
    "channel",
    "question",
    "status",
    "error",
    "message",
    "cost_usd",
    "unpriced_requests",
    "security_events",
    "incidents",
    "moderator_case",
    "limitations",
    "claims",
    "unchecked_claims",
)
CSV_COLUMNS = (
    "time",
    "started_at",
    "channel",
    "status",
    "error",
    "latency_ms",
    "cost_usd",
    "question",
    "claims",
    "verdicts",
    "source_urls",
    "security_events",
    "incidents",
    "moderator_case",
)


def log_records(start: date | None, end: date | None) -> list[dict]:
    """Masked records ended on `start`..`end` (UTC days, both included), newest last, within
    retention and at most MAX_ROWS (the newest ones)."""
    today = datetime.now(UTC).date()
    start = start or today - timedelta(days=RETENTION_DAYS)
    end = end or today
    lo = datetime.combine(start, time.min, UTC)
    hi = datetime.combine(end + timedelta(days=1), time.min, UTC)
    rows = [
        r for r in checklog.read_all() if lo <= datetime.fromisoformat(r["time"]) < hi
    ]
    return [{k: r.get(k) for k in LOG_FIELDS} for r in rows[-MAX_ROWS:]]


def _cell(value) -> str:
    """One CSV cell. A cell a spreadsheet would read as a formula gets a leading apostrophe."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def log_csv(records: list[dict]) -> str:
    """One row per check; the claims, verdicts and source URLs of a check are joined with " | "."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for r in records:
        claims = r["claims"] or []
        row = {
            **r,
            "claims": " | ".join(c["claim"] for c in claims),
            "verdicts": " | ".join(c["verdict"] for c in claims),
            "source_urls": " | ".join(s["url"] for c in claims for s in c["sources"]),
            "security_events": len(r["security_events"] or []),
            "incidents": " | ".join(r["incidents"] or []),
            "moderator_case": (r["moderator_case"] or {}).get("id"),
        }
        writer.writerow(_cell(row[k]) for k in CSV_COLUMNS)
    return out.getvalue()
