"""Shared contract between channels and the verification pipeline."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, HttpUrl, model_validator


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
    verdict: Verdict
    reasoning: str
    # Type of strength is not decided yet (scale, label or score); plain string until it is.
    strength: str
    premises: list[str]
    sources: list[Source]
    limitations: list[str]


class CheckResult(BaseModel):
    status: Status
    message: str | None = None
    claims: list[ClaimResult] = []

    @model_validator(mode="after")
    def _non_ok_is_a_notice(self) -> "CheckResult":
        if self.status is not Status.OK and (self.claims or not self.message):
            raise ValueError("non-ok status needs a message and no claims")
        return self
