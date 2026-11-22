<p align="center">
  <img src="docs/readme/banner.png" alt="faktczyfejk.pl: sprawdź, zanim podasz dalej" width="100%">
</p>

<p align="center">
  <b><a href="https://faktczyfejk.pl">faktczyfejk.pl</a></b> · HackNation 2026, challenge <b>Prawdowid</b><br>
  Michał Furgała · Łukasz Lenkiewicz · Dominik Galus
</p>

# faktczyfejk

A citizen pastes a message or a link, and faktczyfejk answers claim by claim, in Polish, with one of five verdicts:
`potwierdzone`, `fałszywe`, `wprowadzające w błąd`, `brak wystarczających dowodów` or `nie podlega weryfikacji`.
Each source in the answer comes with a link and a quote that the code found word for word in the cited text (for a
fact-checker's review, its rating). When the evidence is not enough, the answer for that claim starts with
"Nie udało mi się potwierdzić tej informacji." and gives the reasons. Claude reads the text and the sources, and
rules in code set the verdict.

## How it works

1. The input is a text of up to 5000 characters or a link. The API fetches a link (HTML or PDF, public addresses
   only, `prawdowid/link.py`) and checks its main text like pasted text. A page it cannot read (paywall, login wall,
   social media) comes back as `cannot_check` with a request to paste the text. E-mail addresses and PESEL, ID
   card, passport, phone, account and card numbers are masked before the text goes to a model.
2. Claude, through PydanticAI, splits the text into claims and marks which ones can be checked. Up to 3 get a full
   check (`PRAWDOWID_MAX_CHECKED_CLAIMS`) and the rest are listed without a verdict. An opinion or a forecast gets
   `nie podlega weryfikacji`.
3. Each checked claim goes to five sources in parallel: Google Fact Check Tools, the www.gov.pl site search, Tavily
   web search on allowlisted domains (`prawdowid/websearch.py`), our corpus of 1158 documents
   (`corpus/evidence.jsonl`, BM25 in memory) and EUvsDisinfo, which is context only and never decides alone.
4. A model ranks the fragments, and a judge model labels each one as supporting, refuting, adding context or showing
   a data gap, with an exact quote. The code drops every quote it cannot find verbatim in the cited document
   (`prawdowid/judge.py`).
5. `judge.decide()` sets the verdict from the quotes that are left: how many independent sources back each side, and
   whether one of them is official, primary or a fact-checker. Without enough evidence the verdict is
   `brak wystarczających dowodów`. When a source that could decide (Fact Check, the web search, or www.gov.pl for a
   claim about the government) is down and the rest is not enough, the claim is `nie sprawdzono` with the outage as
   the reason. An answer in which every checked claim ended that way is a technical error.

## Results

Full run of our eval on `df74cef`, 22.11.2026 ([`latest.json`](evals/results/latest.json), stamped `f4c9aa8`,
which is `df74cef` plus eval results). We wrote the cases and labels. The targets come from the brief.

| Metric | Target | Result |
|---|---|---|
| Verdict accuracy, macro-F1 | ≥ 0.75 | 0.888 |
| Citation coverage | ≥ 0.95 | 1.0 |
| Citation correctness | ≥ 0.85 | 1.0 (checks only that the quote is in the corpus document) |
| Correct abstention | ≥ 0.80 | 1.0 |
| Prompt-injection resistance | ≥ 0.90 | 1.0 (injection in the input text only) |
| Median time, text and URL | ≤ 30 s | 16.0 s |
| End-to-end scenarios without the team | 1.0 | 0.973, below target: J01 and A15 fail |
| Channel consistency | 1.0 | 1.0 |
| Moderator loop | 1.0 | 1.0 |
| Cost of 100 checks | reported | 3.54 USD, model calls only |

75 cases. E05 to E15 (injection in a fetched page) were skipped because they need a public address for the test
pages. Every run with its commit: [HISTORY.md](evals/results/HISTORY.md). A spot check of 12 sampled citations
found the quote or rating on the page for 11, and 10 fit the verdict shown:
[citation_spotcheck.md](evals/results/citation_spotcheck.md).

## Requirements

The table describes the code, not what runs on faktczyfejk.pl. Done means it works in the code and has a test or a
measurement. Partial means it works, with the gap named.

| Requirement | Status | Where |
|---|---|---|
| End-to-end without help from the team | Partial: the code has no manual step, but the full run scores 0.973 (J01, A15) | [docs/eval-notes.md](docs/eval-notes.md) |
| No fabricated sources | Done: the verdict rests on quotes the code found in the cited document, or on a fact-checker's rating of the same claim. The model only labels quotes | [`prawdowid/judge.py`](prawdowid/judge.py) |
| Abstention without evidence | Done: `judge.decide()` returns `brak wystarczających dowodów` without a verified quote from a strong enough source, 1.0 in the full run | [`tests/test_judge.py`](tests/test_judge.py) |
| Two channels, or a channel and a demo adapter | Partial: the web page, the `/czat` demo adapter and the Discord bot `/sprawdz` call the same `POST /api/checks`. Per [#59](https://github.com/00200200/HackNation2026/issues/59) the bot is not deployed (we did not check) | [`czat.js`](frontend/public/czat.js), [`discord_bot.py`](prawdowid/discord_bot.py) |
| Masking and retention | Partial: the personal data listed in step 1 is masked before the model and in every log. Names and addresses are not. The check log keeps 30 days, and "Usuń moje sprawdzenia" deletes a session | [docs/privacy.md](docs/privacy.md) |
| Prompt injection | Partial: code screens the input, the linked page and the retrieved sources for injected instructions, and the prompts mark source text as data. 1.0 on injected input text, page cases E05 to E15 not run | [docs/submission/risks.md](docs/submission/risks.md) |
| Outage not shown as a verdict | Partial: a missing model key, the rate limit or a timeout gives a notice, and a down source that could decide gives `nie sprawdzono`. J01 fails: under a simulated Fact Check outage the answer names it but gives verdicts from the other sources | [docs/unsupported.md](docs/unsupported.md#awarie-i-limity) |
| Moderator loop | Partial: cases are filed and grouped only while `PRAWDOWID_ADMIN_TOKEN` is set (on the demo server: UNCONFIRMED). 1.0 on H01 and H02 | [`prawdowid/cases.py`](prawdowid/cases.py) |

What the product does not support and the message the user sees then: [docs/unsupported.md](docs/unsupported.md)
(Polish). Submission documents: [architecture](docs/submission/architecture.md), [sources](docs/submission/sources.md),
[risks](docs/submission/risks.md), [cost](docs/submission/cost.md), [pilot](docs/submission/pilot.md) (Polish),
[privacy](docs/privacy.md). Open work and decisions: [WORKLOG.md](WORKLOG.md).

## Run

You need Docker with Compose. Put the keys in `.env` in the repository root. Git ignores the file and the image
does not include it.

| Variable | What it is for |
|---|---|
| `ANTHROPIC_API_KEY` | Required. Without it every check returns `technical_error`. |
| `GOOGLE_FACTCHECK_API_KEY`, `TAVILY_API_KEY` | Fact Check and web search. Without them these sources count as down, so a claim without enough other evidence is `nie sprawdzono`. |
| `EUVSDISINFO_API_KEY` | EUvsDisinfo context. Without it that lookup is skipped. |
| `PRAWDOWID_ADMIN_TOKEN` | Bearer token for the moderator queue (`GET /api/cases`). Without it no case is filed and the route answers 404. |
| `PRAWDOWID_MODEL` | Extraction model as PydanticAI `provider:model`, default `anthropic:claude-sonnet-5-5`. The rerank and judge models have their own variables, which Compose does not pass on. |

```bash
make up      # http://localhost:8080, make up PORT=9000 for another port, make down to stop
```

Without `make`: `docker compose up --build -d`. `make up DISCORD=1` also starts the Discord bot, which needs
`DISCORD_BOT_TOKEN`. For the API alone, install [uv](https://docs.astral.sh/uv/getting-started/installation/), then
run `make install` and `make dev` (http://127.0.0.1:8000, docs at `/api/docs`, `.env` loaded). `make check` runs
`ruff format --check`, `ruff check` and `pytest`, and `make help` lists every target. Tuning settings are
`PRAWDOWID_*` variables with defaults in the code, and Compose passes on only the ones in `compose.yaml`. Default
limits: [architecture.md](docs/submission/architecture.md#default-limits-not-performance-measurements). Deployment
with HTTPS: [docs/deploy.md](docs/deploy.md).

Eval, against the API from `make dev`:

```bash
PRAWDOWID_URL=http://127.0.0.1:8000 uv run python -m evals.run --quick                          # one case per scenario
PRAWDOWID_URL=http://127.0.0.1:8000 uv run python -m evals.run --corpus corpus/evidence.jsonl   # full set
```

Some cases need more setup, or they are skipped or fail. The simulated outages (scenario J) need
`PRAWDOWID_EVAL_TOKEN` on the API and in the harness (leave it unset on the public demo), the channel cases (G)
`PRAWDOWID_EXTRA_CHANNELS=discord,demo`, the moderator cases (H) `PRAWDOWID_ADMIN_TOKEN` on the API, and E05 to E15
`PRAWDOWID_FIXTURE_BASE`, a public address of the test pages. Each run writes `evals/results/latest.json` and a row
in HISTORY.md. Details: [`.claude/skills/prawdowid-eval/SKILL.md`](.claude/skills/prawdowid-eval/SKILL.md).

## API

- `POST /api/checks`: body `{"input": "..."}`, a text or a link of 1 to 5000 characters, returns `CheckResult`. A
  channel names itself in `X-Channel` and sends back the `X-Session-Id` it got. 10 requests per minute per client IP.
- `GET /api/sources`: every source a check uses, shown on the page `/zrodla`.
- `GET /api/sessions/{id}` and `DELETE /api/sessions/{id}`: read or delete the masked check records of a demo
  session. Delete also takes the session's questions out of the moderator cases.
- `GET /api/cases`: the moderator queue, with `Authorization: Bearer <PRAWDOWID_ADMIN_TOKEN>`. It answers 404 when the
  variable is unset and 401 on a wrong token, and it is left out of the OpenAPI spec.
- `GET /api/docs` and `GET /api/openapi.json`: Swagger UI and the spec, with a copy in
  [`docs/openapi.json`](docs/openapi.json) that `make openapi` regenerates.
- `GET /health`: liveness.

## Team and license

Team: Michał Furgała, Łukasz Lenkiewicz, Dominik Galus.

License: the repository has no license file. Licenses of the corpus sources:
[docs/corpus.md](docs/corpus.md#licences-and-what-we-store).
