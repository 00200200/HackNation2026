"""Shared contract between channels and the verification pipeline."""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, computed_field, model_validator


class Verdict(StrEnum):
    CONFIRMED = "confirmed"
    FALSE = "false"
    MISLEADING = "misleading"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_VERIFIABLE = "not_verifiable"
    # Not a verdict: the time limit ran out or every source failed. Limitations say which.
    NOT_CHECKED = "not_checked"

    @property
    def label(self) -> str:
        return VERDICT_LABELS[self]


VERDICT_LABELS = {
    Verdict.CONFIRMED: "potwierdzone",
    Verdict.FALSE: "fałszywe",
    Verdict.MISLEADING: "wprowadzające w błąd",
    Verdict.INSUFFICIENT_EVIDENCE: "brak wystarczających dowodów",
    Verdict.NOT_VERIFIABLE: "nie podlega weryfikacji",
    Verdict.NOT_CHECKED: "nie sprawdzono",
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
    # Google Fact Check ClaimReview: the fact-checker's own rating ("Fałsz", "Manipulacja", ...)
    # of `reviewed_claim`. Shown to the judge as a signal, never a verdict.
    rating: str | None = None
    reviewed_claim: str | None = None


class ModelCall(BaseModel):
    """One model answer, kept in the check log only."""

    model: str | None
    input_tokens: int
    output_tokens: int


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
    # Check log only (prawdowid/checklog.py): never sent to a channel.
    steps_ms: dict[str, int] = Field(default={}, exclude=True)

    @computed_field
    @property
    def verdict_label(self) -> str:
        return self.verdict.label


class MatchKind(StrEnum):
    """How the input matched a known incident, strongest first."""

    URL = "url"
    DOMAIN = "domain"
    TEXT = "text"


class IncidentMatch(BaseModel):
    """A known incident the input looks like (scenario I). Context only, never a verdict."""

    incident_id: str
    incident_text: str
    matched_on: MatchKind
    url: str | None = None
    # Text similarity 0..1 (difflib ratio), only for a text match.
    similarity: float | None = None


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
    # "patterns": our fixed phrase list in code; "defender": StackOne Defender's pattern tier on a
    # retrieved page (`prawdowid/injection.py`); "model": a model's own flag (extraction or judge).
    detector: Literal["patterns", "defender", "model"]


class ModeratorAnswer(BaseModel):
    text: str
    answered_at: datetime


class CheckResult(BaseModel):
    status: Status
    message: str | None = None
    # Set when the input was a link and the page was fetched.
    page: CheckedPage | None = None
    claims: list[ClaimResult] = []
    # Claims found but left out by the per-check cap. They have no verdict.
    unchecked_claims: list[str] = []
    security_events: list[SecurityEvent] = []
    # Limits of the check as a whole, e.g. injection detection ran on patterns only.
    limitations: list[str] = []
    # Model tokens plus paid API calls for this answer; None when it cannot be known.
    cost_usd: float | None = None
    # Shown next to the claims, also on a notice (a refused link): never sets or changes a verdict.
    incident_matches: list[IncidentMatch] = []
    # Scenario H: the main claim had no evidence, so the question went to a moderator. The same
    # question asked again gets the same case (prawdowid/moderation.py).
    moderator_case_id: str | None = None
    # A moderator's note on that case, shown next to the result: never sets or changes a verdict.
    moderator_answer: ModeratorAnswer | None = None
    # Check log only (prawdowid/checklog.py): never sent to a channel.
    steps_ms: dict[str, int] = Field(default={}, exclude=True)
    model_calls: list[ModelCall] = Field(default=[], exclude=True)

    @model_validator(mode="after")
    def _non_ok_is_a_notice(self) -> "CheckResult":
        has_claims = self.claims or self.unchecked_claims
        if self.status is not Status.OK and (has_claims or not self.message):
            raise ValueError("non-ok status needs a message and no claims")
        return self
