# Scenario G: one question, web and Discord

The brief's scenario G sends the same report through the web form and the second channel and
expects the same result. This is one recorded run, not an eval metric.

- Date: 21.11.2026, code at `bcda8d0` plus this branch's Discord changes (#59).
- Setup: the API ran locally (`uvicorn prawdowid.app:app`) with the team's `.env`. Web search did
  not run: the Tavily key in that `.env` did not load, and EUvsDisinfo timed out. Fact Check, the
  www.gov.pl search, rerank and judge ran.
- Web: `POST /api/checks` with `X-Channel: web`, as the form sends it.
- Discord: the bot's own `ask_api()` and `reply()` from `prawdowid/discord_bot.py` (the request with
  `X-Channel: discord` and the messages the bot would post). No live Discord transport: there was
  no bot token yet.

Input: „Czy Wrocław był jedynym miastem w Polsce, w którym 65-latkowie jeździli komunikacją miejską
za darmo?”

| | Web | Discord |
|---|---|---|
| Status | `ok` | `ok` |
| Claim | Wrocław był jedynym miastem w Polsce, w którym 65-latkowie jeździli komunikacją miejską za darmo. | the same |
| Verdict | `brak wystarczających dowodów` | `brak wystarczających dowodów` |
| Sources | none | none |

Both channels gave the same claim and verdict. With web search down this is the "no evidence"
path: the run shows that the channels agree and says nothing about whether the answer is right. Nothing makes the two
answers agree by design: each request runs the whole pipeline again, so a run with real evidence
can still split claims or rate them differently (issue #59, review comment).

The message the bot would post (one message, no attachment):

```
### 1. Wrocław był jedynym miastem w Polsce, w którym 65-latkowie jeździli komunikacją miejską za darmo.
-# W tekście: Czy Wrocław był jedynym miastem w Polsce, w którym 65-latkowie jeździli komunikacją miejską za darmo?
Ocena: **brak wystarczających dowodów**
**Uzasadnienie:** Twierdzenie dotyczy zasad taryfowych komunikacji miejskiej w polskich miastach, które można porównać z uchwałami i cennikami przewoźników.
**Siła dowodów:** brak
**Przesłanki:**
**Źródła:**
- brak
**Ograniczenia:**
- Wyszukiwanie w bazie EUvsDisinfo było niedostępne, więc nie sprawdziliśmy, czy to twierdzenie powtarza znany przypadek dezinformacji.
- Wyszukiwarka internetowa nie odpowiedziała albo nie zwróciła wyników, więc nie szukaliśmy źródeł w sieci.
- Nie znaleźliśmy źródeł na temat tego twierdzenia.
```

Still to record: the same question sent with `/sprawdz` in the real test server, and on
https://faktczyfejk.pl once the server has its API keys (#58).
