"""Shared contract between channels and the verification pipeline."""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, computed_field, model_validator


class Verdict(StrEnum):
    """Outcome for one claim.

    `not_checked` is not a verdict: the time limit ran out, every source failed, or the
    judge model did not answer, and the claim's limitations say which.
    """

    CONFIRMED = "confirmed"
    FALSE = "false"
    MISLEADING = "misleading"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_VERIFIABLE = "not_verifiable"
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


class SourceStance(StrEnum):
    """Which side of the claim a source stands on, for the evidence chain (#78)."""

    SUPPORTS = "potwierdza"
    REFUTES = "przeczy"
    CONTEXT = "kontekst"


class Source(BaseModel):
    title: str
    publisher: str
    published_at: date | None
    fetched_at: datetime
    url: HttpUrl
    source_type: str
    # The source's own words that the verdict rests on. With `rating` set, it is that rating in
    # the wording of the fact-checker's ClaimReview record, not text of the review page.
    fragment: str | None = None
    # Set when we could not read the page ourselves: the text is the search provider's extract of
    # it, and `fetched_at` is when we searched. Says why, in Polish ("strona nie pozwala na pobranie").
    snippet_only: str | None = None
    # A fact-checker's rating of the checked claim (`textualRating` of its ClaimReview record).
    # Channels show it as the fact-checker's rating, never as a quote from its page.
    rating: str | None = None
    # Set only by `judge.decide()`, from a label whose quote was found verbatim in this source.
    stance: SourceStance | None = Field(
        None,
        description="The side this source stands on, from a quote found verbatim in it: "
        "'potwierdza' (confirms the claim), 'przeczy' (contradicts it) or 'kontekst' (adds "
        "context, a data gap or a fact-checker's review of another claim). A fact-checker's "
        "rating of this claim gives its side through the rating. null when the verdict rules "
        "did not count the source: a headline alone, an older rating by the same "
        "fact-checker, or a source that says both.",
    )


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


class CheckedImage(BaseModel):
    """The screenshot or photo the user sent (scenario F, prawdowid/image_input.py). A model read
    its text, which was then checked like pasted text. The image itself is never stored."""

    sha256: str
    # The text the model read, personal data masked: what was checked. None when the image could
    # not be read (the answer is then a notice); "" when it holds no text.
    text: str | None = None
    # A date shown in the image, as printed ("12 marca 2026", "3 godz."), when the model saw one.
    visible_date: str | None = None
    # From the file's EXIF metadata, when it has any: context only, never used for a verdict.
    # Messengers usually strip it, so a missing value says nothing about the image.
    taken_at: str | None = None
    camera: str | None = None


class SecurityEvent(BaseModel):
    """Instructions aimed at the model were found and ignored. Never carries their wording."""

    kind: Literal["prompt_injection"] = "prompt_injection"
    # Where they were found: "input" (the user's text), "page" (the page a link points to),
    # "image" (text read from an image the user sent) or "source" (a retrieved evidence page).
    location: Literal["input", "page", "image", "source"]
    # "patterns": the fixed pre-check in code; "model": a model's own flag (extraction or judge).
    detector: Literal["patterns", "model"]


class ModeratorCase(BaseModel):
    """The moderator's case this question was added to (scenario H, prawdowid/cases.py). Set only
    after the case was written, so a channel says the question went to the moderator's queue only
    when it did."""

    id: int
    # "created": this question opened the case; "updated": it joined an open one.
    status: Literal["created", "updated"]
    # Questions in the case within the retention period, this one included.
    count: int


class CheckResult(BaseModel):
    status: Status
    message: str | None = None
    # Set when the input was a link and the page was fetched.
    page: CheckedPage | None = None
    # Set when the input had an image; its limitations are in `limitations`.
    image: CheckedImage | None = None
    claims: list[ClaimResult] = []
    # Claims found but left out by the per-check cap. They have no verdict.
    unchecked_claims: list[str] = []
    security_events: list[SecurityEvent] = []
    # Limits of the check as a whole, e.g. injection detection ran on patterns only.
    limitations: list[str] = []
    # Priced sum of the model requests answered for this answer (tokens only: search credits are
    # not priced), always a number. `unpriced_requests` counts requests that may be billed but
    # have no price (cut, failed, unpriced model); above 0, cost_usd is a lower bound.
    cost_usd: float = Field(
        0.0,
        description="Priced sum of the model requests answered for this answer, in USD (search "
        "credits excluded). A lower bound when unpriced_requests is above 0.",
    )
    unpriced_requests: int = Field(
        0,
        description="Model requests that may be billed but have no price (cut, failed or refused, "
        "or an unpriced model). Above 0, cost_usd is a lower bound.",
    )
    # Shown next to the claims, also on a notice (a refused link): never sets or changes a verdict.
    incident_matches: list[IncidentMatch] = []
    moderator_case: ModeratorCase | None = Field(
        None,
        description="The moderator case this question was stored in: a claim without enough "
        "evidence, a security event, or an unconfirmed claim on a high-risk topic. null when "
        "nothing was stored: the check needed no person, no moderator queue is set up on this "
        "server, or the case store failed. A channel then says nothing about a moderator.",
    )
    # Check log only (prawdowid/checklog.py): never sent to a channel.
    steps_ms: dict[str, int] = Field(default={}, exclude=True)
    model_calls: list[ModelCall] = Field(default=[], exclude=True)

    @model_validator(mode="after")
    def _non_ok_is_a_notice(self) -> "CheckResult":
        has_claims = self.claims or self.unchecked_claims
        if self.status is not Status.OK and (has_claims or not self.message):
            raise ValueError("non-ok status needs a message and no claims")
        return self
