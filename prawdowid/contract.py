"""Shared contract between channels and the verification pipeline."""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, HttpUrl, computed_field, model_validator


class Verdict(StrEnum):
    CONFIRMED = "confirmed"
    FALSE = "false"
    MISLEADING = "misleading"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_VERIFIABLE = "not_verifiable"

    @property
    def label(self) -> str:
        return VERDICT_LABELS[self]


VERDICT_LABELS = {
    Verdict.CONFIRMED: "potwierdzone",
    Verdict.FALSE: "fałszywe",
    Verdict.MISLEADING: "wprowadzające w błąd",
    Verdict.INSUFFICIENT_EVIDENCE: "brak wystarczających dowodów",
    Verdict.NOT_VERIFIABLE: "nie podlega weryfikacji",
}


class Status(StrEnum):
    """Outcome of the check itself. Never shown as a verdict."""

    OK = "ok"
    TECHNICAL_ERROR = "technical_error"
    CANNOT_CHECK = "cannot_check"
    NEEDS_CLARIFICATION = "needs_clarification"


class ClaimKind(StrEnum):
    """A quote "X said that Y" gives two claims: that X said it, and Y as quoted content."""

    STATEMENT = "statement"
    ATTRIBUTION = "attribution"
    QUOTED = "quoted"


class Source(BaseModel):
    title: str
    publisher: str
    published_at: date | None
    fetched_at: datetime
    url: HttpUrl
    source_type: str
    fragment: str | None = None


class ClaimResult(BaseModel):
    claim: str
    kind: ClaimKind
    # Sentence of the input the claim comes from: shows what was checked, never evidence.
    source_sentence: str
    verdict: Verdict
    reasoning: str
    # Type of strength is not decided yet (scale, label or score); plain string until it is.
    strength: str
    premises: list[str]
    sources: list[Source]
    limitations: list[str]

    @computed_field
    @property
    def verdict_label(self) -> str:
        return self.verdict.label


class CheckedPage(BaseModel):
    """The page a link pointed to. Its own URL is never evidence for its own claims."""

    url: str
    sha256: str
    title: str | None
    publisher: str | None
    published_at: date | None


class SecurityEvent(BaseModel):
    """Instructions aimed at the model were found and ignored. Never carries their wording."""

    kind: Literal["prompt_injection"] = "prompt_injection"
    # Where they were found: "input" (the user's text), "page" (the page a link points to) or
    # "source" (a retrieved evidence page).
    location: Literal["input", "page", "source"]


class CheckResult(BaseModel):
    status: Status
    message: str | None = None
    # Set when the input was a link and the page was fetched.
    page: CheckedPage | None = None
    claims: list[ClaimResult] = []
    # Claims found but left out by the per-check cap. They have no verdict.
    unchecked_claims: list[str] = []
    security_events: list[SecurityEvent] = []
    # Model tokens plus paid API calls for this answer; None when it cannot be known.
    cost_usd: float | None = None

    @model_validator(mode="after")
    def _non_ok_is_a_notice(self) -> "CheckResult":
        has_claims = self.claims or self.unchecked_claims
        if self.status is not Status.OK and (has_claims or not self.message):
            raise ValueError("non-ok status needs a message and no claims")
        return self
