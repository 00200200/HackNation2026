# ADR 0001: Evidence retrieval and verdict flow

- Status: accepted for sections 1–4 (Michał, 2026-11-21); sections 5–6 proposed, waiting for a team OK before the first
  push that implements them
- Diagram: board "Architektura" on https://claude.ai/artifact/3f8LsRGUNnpgVAhAEsZcgu (private until shared)
- Brief: "PRAWDOWID: szybka i łatwa weryfikacja informacji" (MSZ, HackNation 2026), sections cited as §n
- Reviewed: independent check against the brief on 2026-11-21; its blockers (single-source verdicts, scenario C,
  strength premises, dependencies, outage vs abstention) are addressed below

## Context

The brief sets hard limits on how we find evidence and decide a verdict:

- Search a shared or clearly described set of sources; the demo corpus has at least 100 documents, 10 domains and two
  source types (primary or official, plus reliable secondary). The source list must be auditable (§5 Źródła).
- Store publication and retrieval timestamps, prefer current data, warn about archival material (§5 Aktualność).
- Median time from input to answer at most 30 s for text or URL; cost of 100 tests reported (§6).
- Every source shows at least title, publisher, date and link, and the quoted fragment where possible (§2).
- Verdict strength comes from explicit premises: source quality and freshness, match with the claim, number of
  independent confirmations (§2).
- Not enough evidence means abstaining and saying what could not be established (§2, §3, scenario D). Two reliable
  sources that disagree are shown as a disagreement, without arbitrary certainty (scenario C).
- Forbidden: deciding truth from the domain, author, channel, popularity, share count or a label made by the same model;
  letting a source's status, including EU sanctions, decide truth (a separate neutral warning is allowed when current,
  verifiable and relevant). The presence of a domain or channel in an incident catalogue is never the basis of a
  verdict, but may trigger a warning in explicitly defined cases (§3, §5 Ograniczenia, scenario I).
- Instructions found in analysed material never change the rules, and the attempt is recorded (§2, scenario E).
- A technical failure, an impossible check and a request to clarify are not verdicts and are shown separately (§2). A
  missing key, limit or outage is never presented as a factual result (§5, scenario J).
- Required keys, limits, costs, data location and failure behaviour of external services are described (§5).
- Channels are separated from the verification logic; the model or provider can be swapped (§5 Architektura).

The team first proposed a sequential chain: a link is scraped, a message is checked by scraping the listed domains,
fact-check databases cover fakes, the listed domains cover facts, then internet search, then "not enough evidence".

## Decision

### 1. Sources are indexed before a check, not scraped during it

A catalogue lists each source with domain, publisher, source type, licence, update interval and date added. A
scheduled job fetches pages, extracts main text and dates with trafilatura, and writes fragments with publication and
retrieval timestamps to a local index (BM25 plus embeddings). Checks search this index; they never crawl the listed
domains.

Source types, from strongest to weakest: official or primary (gov.pl services, Policja, CERT Polska, IMGW, Sejm ELI),
fact-checkers following IFCN or EFCSN, the incident base (EUvsDisinfo cases, the organiser's base), allowlisted media.

Catalogue rules, published with the source list:

- Admit: official Polish or EU bodies; fact-checkers with current IFCN or EFCSN status; the organiser's incident base;
  media only when the team agrees and records why. Every entry needs a licence or terms that allow storing a short
  fragment with a link.
- Update: each entry has an interval; the job records the last successful fetch; a fragment keeps its own dates.
- Exclude: a dead or blocked source for longer than one interval, a lost IFCN or EFCSN status, terms that no longer
  allow storage. Excluded entries stay in the list with the reason and date.
- Target for the demo: at least 100 documents from at least 10 registered domains and both source types. Checking
  these counts in the eval run is planned: `evals/run.py` reads only each document's URL and text today.

### 2. One check, step by step

Design time budget (to be measured, not a result): claim extraction up to 8 s, parallel retrieval up to 5 s per source,
stance and citation check up to 12 s, fallback search only if less than 15 s have passed.

1. Input guard: validation, rate limit, masking of obvious personal data, detection of instructions inside the text.
   A detected attempt is logged as a security event and the answer says that this part of the text was ignored.
2. Link input: fetch the page (timeout, SSRF protection), keep its text, date and address. The address also goes to the
   known-domain check (section 5).
3. Claim extraction (LLM, no tools; user text and fetched pages enter the prompt as delimited data): fact or opinion,
   time and place anchors, two or three questions per claim, search queries in Polish and English. Opinions and
   forecasts get `nie podlega weryfikacji`.
4. Parallel retrieval, each source with its own timeout: official corpus, Google Fact Check Tools API (the quote is then
   taken from the fact-check article itself), incident base, live official APIs such as IMGW warnings. A source that
   fails or times out is listed in `limitations`; it is never evidence of anything.
5. Merge: remove duplicates, prefer different publishers, keep 10–15 fragments with IDs.
6. Stance (LLM, no tools, fragments as delimited data): for each fragment, supports, refutes or unrelated, plus whether
   its time and place match the claim's anchors.
7. Citation check: the quote must appear verbatim in the stored fragment, then a separate judge confirms it supports or
   refutes the claim as labelled. Failing quotes are dropped. Each kept citation has title, publisher, publication
   date (or "no date", which lowers strength), retrieval date, URL, quote and the quote's language; the explanation is
   in Polish and a quote in another language is marked as such.
8. Verdict in code from the rules in section 3. The model never states the verdict.
9. Not enough evidence and time left: one round of web search restricted to the allowlisted domains; fetched pages are
   untrusted data and go through steps 5–8.
10. Still not enough: `brak wystarczających dowodów`, the list of what was not established (the unanswered questions
    from step 3), and a moderator case, deduplicated with earlier similar questions.
11. Response and log: question (masked), time, sources used, result, model, tokens, cost, security events.

Technical failures are not abstentions. If the LLM call fails, or the official corpus cannot be searched, the answer
has status `technical_error` with a plain message and no claims. If only an external source fails, the check goes on
and that source is listed in `limitations`. A text too vague to contain a claim gets `needs_clarification`.

### 3. Verdict rules (starting point, thresholds tuned on the eval set)

A citation is "verified" when it passed step 7. "Matching" means the stance step found that its time and place agree
with the claim. "Stale" means the fragment is older than the freshness limit of its source type when the claim is
about the present (for example days for weather and safety warnings, the date of the last amendment for law).

- Different measures are not a disagreement: the stance step first checks whether two citations describe the same
  thing (same quantity, period, place and definition). If they do not, for example an estimate quoted by a politician
  against one budget line for one year, the answer explains the difference and relies on the more specific source
  (mentor guidance, scenario C).
- Disagreement: if verified supporting and refuting citations from sources of the first three types describe the same
  thing, the verdict is `brak wystarczających dowodów` and both sides are shown. Source type never settles a
  disagreement; it only lowers strength.
- A fact-checker's own rating is reported with attribution and its exact wording ("Demagog ocenił to jako częściową
  prawdę"), and maps to our classes: Prawda to `potwierdzone`, Fałsz to `fałszywe`, Manipulacja, Częściowa prawda and
  Częściowy fałsz to `wprowadzające w błąd`, Nieweryfikowalne to `brak wystarczających dowodów`. The mapping is
  provisional and checked on the eval set. The rating comes from Google Fact Check, the corpus or, since #127, the
  ClaimReview markup of a review page we read (a Fact Check hit with a rating for the same page wins; the page's text
  after the rating is read as the page's own, not as the rating), and is looked up with case and diacritics folded
  (Demagog also writes "Falsz"). A fact-checker's own verdict sentence on the page or in its search snippet
  ("…wypowiedź oceniamy jako fałsz", "…uznajemy za nieweryfikowalną") counts as its rating when the stance step marks it
  as the fact-checker's own conclusion. A fact-checker's Nieweryfikowalne, or any of its sentences the stance step
  labels a data gap, decides `brak wystarczających dowodów` unless a fact-checker's own conclusion takes a side or a
  reliable source published after that finding does: an older or undated page never turns the gap into a verdict (22.11, after the
  round-4 full run, where FC-D01, FC-D02 and FC-D03 lost Demagog's "nieweryfikowalne" to other sources). Of one
  fact-checker's ratings of the same claim the newest counts (a later review updates an earlier one), and an older
  rating in other words is listed with a note naming the newer one; two fact-checkers whose ratings disagree are a
  disagreement (above).
- `potwierdzone`: verified matching supporting citations from at least two independent publishers, or from one
  official source when it is not stale. With one source the strength is "low" or "medium" and the answer says that only
  one source confirms it. A search snippet of a page we could not read confirms alone only when it is a fact-checker's
  own conclusion; any other snippet needs a second independent publisher, and the answer says why (#127). Refuting
  rules do not change for snippets.
- `fałszywe`: a verified refuting citation from an official source or a fact-checker whose reviewed claim the stance
  step matched to ours, and no verified supporting citation.
- `wprowadzające w błąd`: verified supporting citations exist, but the stance step marks a time or place mismatch, or
  the only support is stale while the claim presents it as current (scenarios B and archival material). A mismatch
  named on a context citation counts only from a fact-checker or from a source that also supports or refutes the
  claim: a page that takes no side shows its own scope (another year, region or alert level), not what the claim
  leaves out (#127).
- No verified citation: `brak wystarczających dowodów`.

Strength is computed in code and returned with its premises, using the fields that already exist in the contract
(`strength`, `premises`, `limitations` on `ClaimResult`): high, medium or low from the number of independent
publishers, source types, freshness and whether any source failed. Each premise is one plain sentence, for example
"Dwa niezależne źródła, w tym jedno urzędowe" or "Najnowsze źródło ma 3 lata". A stale citation adds an archival
warning to `limitations`.

### 4. Fallback search is limited to trusted domains

Open internet search was rejected (see Alternatives). The fallback uses one search API with a domain filter, one round,
only within the time budget.

### 5. Known disinformation domains trigger a warning, never a verdict (proposed)

Question from the team: if a claim appears on a domain known for fakes or deepfakes, should we call it fake?

No. The brief forbids it, and it would also be wrong in practice: such outlets mix true reports with false ones, so a
true claim found there would get the wrong verdict.

What we do instead:

- Build a list of known disinformation domains from the incident base, e.g. the `linksToDisinformation` URLs of
  EUvsDisinfo cases, with the number of cases per domain and the date the list was built.
- If the user's link, or the page a claim came from, is on that list, show a separate neutral warning: the domain
  appears in N cases of EUvsDisinfo, with a link to them, and a sentence that this does not decide whether this content
  is true. Trigger: at least one case for the exact registered domain. The warning changes neither the verdict nor the
  strength.
- These domains are never evidence and never in the corpus. The claims are still checked against trusted sources.
- Content matching is different from domain matching. A similar case in the incident base is first shown as context.
  Its disproof text counts as a citation only when the stance step matches the reviewed claim to ours and the quote
  passes step 7; on its own it gives at most medium strength.
- Images (premium, later): a match with a known fake image in our local index is shown as context with its source,
  under the same rule.

### 6. EU sanctions status (proposed)

If the user's link or a cited page belongs to an outlet under current EU restrictive measures, the answer may show a
separate neutral note with the legal act and the date we checked it. The list must come from an official EU source and
carry its retrieval date; without a current list there is no note. The note never changes the verdict or strength.

### 7. Answer format (mentor guidance, 2026-11-21)

The mentor shared example questions and model answers for scenarios A–J. Jury questions are conversational ("Czy…?"),
and most model answers rest on Demagog articles, the Google Fact Check index and the Odyseusz portal. The answer:

- starts with a direct reply: "Tak.", "Nie." or "Nie udało mi się tego potwierdzić.", then one or two sentences with
  attribution ("Według Demagoga…", "Rządowy portal Odyseusz podaje…") and the link;
- for time-bound facts, states the date and the limit of what is known ("zapowiedziano na 20 listopada 2026 r.; nie mam
  informacji, czy się odbył");
- when abstaining, names the source that would settle the question and says that absence from our sources is not
  evidence that nothing happened;
- for a screenshot, reads the text and the visible date, and says that a date on an image does not prove the
  publication date;
- for a repeated or paraphrased question, joins the same moderator case and mentions saving only when the system
  confirmed it;
- for a URL, says it is the same material only when title, topic and date agree, and shows that basis; a similar topic
  or the same domain is not enough;
- for a failed external check, names what could not run ("Nie mogę teraz sprawdzić indeksu Google z powodu błędu
  dostępu") and never says that no such article exists;
- answers "Czy Demagog to sprawdzał?" from the fact-check index, with the link to the publication, and gives the same
  verdict and the same publication on the web and on Discord.

Contract consequence: the response needs a short direct answer per claim (proposed field `answer`), built only from
verified citations; the UI shows it first.

## External dependencies

| Service | Used for | Key | Where data goes | On failure |
|---|---|---|---|---|
| LLM through PydanticAI (default `anthropic:claude-opus-5-5`; Mistral on `api.eu.mistral.ai` is an EU option) | steps 3, 6, 7 | yes | provider's region; to be stated per chosen model | `technical_error` |
| Google Fact Check Tools API | step 4 | yes (Google Cloud project) | Google; the masked claim and short keys from it (names, quoted spans of the claim or its source sentence, its search queries), masked again | listed in `limitations` |
| EUvsDisinfo MCP server | step 4, section 5 | token from the organiser | EUvsDisinfo service; only the masked claim text is sent | listed in `limitations` |
| Live official APIs (e.g. IMGW) | step 4 | no | public endpoints; only the query is sent | listed in `limitations` |
| Fallback search API | step 9 | yes | not chosen yet | skipped, listed in `limitations` |
| Embeddings and BM25 | steps 1, 4 | no | local | `technical_error` |

Cost per answer is to be logged from token usage and API calls (step 11) once `cost_usd` is in the contract; the cost
of 100 and 1000 queries will then come from the eval run, not from a hand estimate. Today `evals/run.py` reports
`cost_per_100_usd` only, and it stays empty until answers carry `cost_usd`. Limits and prices are filled in from each provider's page when the provider is
chosen; until then they are unknown, not zero.

## Consequences

- Fast checks: the corpus search is local; only external APIs and the user's link cost network time.
- Auditable: every verdict points to stored fragments with dates; the catalogue is the published source list.
- Freshness is limited by the indexing interval; live APIs and the allowlisted fallback cover part of the gap.
- Fewer confident verdicts on thin evidence: single sources are labelled as such, disagreements are shown.
- New dependencies, listed above. EUvsDisinfo cases are in English, hence the English queries.

## Alternatives considered

- Scraping the listed domains during a check: too slow for 30 s, fragile, and no stored timestamps.
- A sequential chain of sources: slower, and conflicts between sources stay hidden. We do not know in advance whether a
  message is fake, so we cannot pick the "fake" or "fact" source first.
- Open internet search: not a clearly described set of sources, more low-quality pages and injection attempts, one more
  vendor.
- Verdict from the domain's reputation or sanctions status: forbidden by the brief (sections 5 and 6).
- Source type deciding a disagreement: arbitrary certainty, fails scenario C.

## Scenario coverage

| Scenario | Handled by |
|---|---|
| A simple fact | steps 4–8, official corpus |
| B wrong time or place | stance step time and place match, `wprowadzające w błąd` |
| C conflicting sources | same-measure check first; a real disagreement shows both sides |
| D no evidence | steps 9–10 |
| E injection | step 1 detection and note in the answer, delimited data in steps 3 and 6, verbatim check in step 7 |
| F screenshot or photo | not handled yet; the answer says that images are not supported (target in section 7) |
| G same answer on both channels | one `verify()` for web and Discord |
| H repeated question | moderator case with deduplication, step 10 |
| I known incident | section 5 warning, content match as context or checked citation |
| J missing key or outage | `technical_error`, or a limitation when only an external source fails |

## Open questions

- Fallback search API: provider, cost and where data is processed.
- Format of the organiser's incident base, and the EUvsDisinfo token.
- Freshness limits per source type (initial values set with the catalogue, then checked on the eval set).
- Storage for the check log and moderator cases (still UNDECIDED in `WORKLOG.md`).
