# Cost and behaviour under load

This is an extrapolation from a saved test run, not an invoice or a hosting quote.
The only monetary and measured latency inputs below come from
[evals/results/latest.json](../../evals/results/latest.json) (the same file as
`evals/results/history/20261122T021757.182695Z-ca48b84-full.json`), timestamp
`2026-11-22T02:27:29+00:00`, commit `ca48b84390d0df22881024155a37bfafba606ce2` (`integration/r3`),
`mode: "full"`, `n_cases: 75`, `concurrency: 4`, `dirty: false`. The commit is the eval harness's;
which server and code version answered is not recorded (see
[architecture.md](architecture.md#saved-test-results-and-reproduction)). At that commit the code
default extracts claims with Claude Sonnet (#88). The run has `overall_pass: false`; it is not
evidence of production quality or capacity.

## Estimate for 1,000 checks

The recorded `metrics.cost_per_100_usd.value` is exactly `4.272704084507042` USD: the mean of the
per-answer `cost_usd` of the first answer of each case, times 100 (`cost_per_100` in
[evals/run.py](../../evals/run.py)). It rests on 71 priced answers (`n_priced`); the 4 simulated
outages (J01, J02, FC-J01, FC-J02) send no model request and are left out
(`n_simulated_excluded`), no first answer came from the result cache (`n_cached_excluded: 0`) and
none had unpriced requests (`n_incomplete: 0`, `lower_bound: false`). Applying the measured rate:

```text
Estimated USD/check = 4.272704084507042 / 100 = 0.04272704084507042
Estimated USD for 1,000 checks = 0.04272704084507042 * 1000
                              = 42.72704084507042
Rounded display estimate = USD 42.73 for 1,000 checks
```

This assumes the same request mix and retrieval conditions as the saved run: our 75 cases, two of
them links. It prices model usage, including extraction, rerank and judge, through
PydanticAI/genai-prices. On `integration/r3`, `cost_usd` is always a number: the priced sum of the
answered requests. A request that was cut, failed, refused or sent to an unpriced model is counted
in `unpriced_requests`, and above 0 the figure is a lower bound; failed calls may still be billed
([verifier.py](../../prawdowid/verifier.py), [pipeline.py](../../prawdowid/pipeline.py)).
The earlier quick run on `edd34a5` (10 cases, Opus extraction) recorded $4.91 per 100 checks
([HISTORY.md](../../evals/results/HISTORY.md)); it is not used here.

It excludes hosting, network, search fees, Discord operation and tax. Web search is the one fee
with recorded inputs, both older than this run: about 4.9 Tavily credits per check (measured with Tavily; Perplexity pricing and usage are not measured here: UNCONFIRMED) in an 8-case
run before the merge onto `main` (the "#7/#8 live proof" entry in [WORKLOG.md](../../WORKLOG.md)),
and pay-as-you-go at $0.008 a credit (the #7 provider research in the same file). At that rate
1,000 checks would take about 4,900 credits, roughly $39, or $31 after the 1,000 free monthly
credits: UNCONFIRMED for the current code, which runs about four searches for each of up to
three checked claims in one pass, with no retry. Google Fact
Check, EUvsDisinfo and the www.gov.pl search have no recorded fee; their quotas are UNCONFIRMED.
The result file contains an aggregate cost metric, not itemised provider invoices.

The case mix is our test set, not a sample of real traffic. The JSON does not record
per-provider retrieval outcomes, model overrides or MCP credentials. Costs with different claim
counts, retries, different models or all providers succeeding are UNCONFIRMED.

## Channel and infrastructure cost

| Component | Confirmed implementation | Cost status |
|---|---|---|
| Web | nginx and static assets call the shared backend; [compose.yaml](../../compose.yaml), [frontend](../../frontend/public/app.js) | Hosting, bandwidth and domain cost UNCONFIRMED |
| Discord | Persistent discord.py bot calls the same API; [discord_bot.py](../../prawdowid/discord_bot.py). Not running on the server and never run against real Discord ([deploy.md](../deploy.md), section 7) | Platform fees, bot hosting and incremental channel cost UNCONFIRMED; no live channel cost measured |
| Verification through either channel | Same API and models, no channel-specific model pipeline; [app.py](../../prawdowid/app.py) | Applying the measured rate to Discord is an assumption; no measured per-channel cost comparison |
| Google / Perplexity or Tavily / EUvsDisinfo / www.gov.pl | [factcheck.py](../../prawdowid/factcheck.py), [websearch.py](../../prawdowid/websearch.py), [euvsdisinfo.py](../../prawdowid/euvsdisinfo.py), [govpl.py](../../prawdowid/govpl.py) | Tavily: estimate above, UNCONFIRMED. Perplexity: charges and quotas UNCONFIRMED, not measured. The others: charges and quotas UNCONFIRMED. None is a measured `cost_usd` line item |
| Own store | Local opt-in PostgreSQL, disabled in checks; [compose.yaml](../../compose.yaml), [pipeline.py](../../prawdowid/pipeline.py) | Database operation cost UNCONFIRMED; Supabase is not deployed |

The app has no checkout or user billing path ([frontend](../../frontend/public/index.html),
[API](../../prawdowid/app.py)). That does not establish free hosting, free Discord connectivity
or an ongoing operator subsidy. A free-to-user deployment budget remains UNCONFIRMED.

## Latency and load

Saved `metrics.median_latency_s.value`: exactly `17.842587917002675` seconds
([latest.json](../../evals/results/latest.json)), over the first answer of each of the 75 cases,
with up to four cases in flight. By default the eval starts requests at least 6.5 s apart and
excludes that wait from latency ([adapter.py](../../evals/adapter.py)); this is not a concurrency benchmark.
No simultaneous-user capacity, tail latency, saturation point or cost under load is measured:
UNCONFIRMED. We do not extrapolate throughput from this median.

The implemented controls below are configuration, not measured load results. Their numbers come
from the linked code, not from a cost assumption:

- API: `10/minute` per client IP, with HTTP `429` and a Polish notice; outer verification timeout
  `60` seconds ([app.py](../../prawdowid/app.py)). Discord users share the bot's API client IP;
  there is no per-Discord-user quota ([discord_bot.py](../../prawdowid/discord_bot.py)).
- The same input within 30 minutes gets the stored answer from a per-process result cache (at
  most 500 answers), with no model or search calls, whichever channel asks
  ([app.py](../../prawdowid/app.py)).
- Extraction checks at most `3` claims in full and asks for `2` model queries per checkable claim,
  plus the claim sentence and one fact-checker-only search, so about `4` web searches per claim (Tavily credits when Tavily is the provider)
  ([verifier.py](../../prawdowid/verifier.py)). Claims and retrieval calls fan out with
  `asyncio.gather` and `asyncio.TaskGroup`; there is no global queue or daily spend cap, only
  per-process limits on page extraction and gov.pl requests ([pipeline.py](../../prawdowid/pipeline.py),
  [link.py](../../prawdowid/link.py), [govpl.py](../../prawdowid/govpl.py)).
- The whole-check budget is `40` seconds, EUvsDisinfo and the corpus lookup are capped at `5`
  seconds each in the pipeline, and there is no second search pass
  ([pipeline.py](../../prawdowid/pipeline.py)). Extraction has a `45` second provider request
  timeout, but shares the `40` second whole-check deadline with URL fetching and claim checks
  ([verifier.py](../../prawdowid/verifier.py)). These are configured cancellation limits, not a
  measured capacity guarantee.
- Web queries are capped at `10` seconds including the provider's retry, page fetches at `8` seconds
  ([websearch.py](../../prawdowid/websearch.py)), the gov.pl search at `10` seconds
  ([govpl.py](../../prawdowid/govpl.py)) and Fact Check at `15` seconds
  ([factcheck.py](../../prawdowid/factcheck.py)). Cancellation of a thread-backed search does not
  stop its underlying synchronous work immediately. Slow providers can consume resources after
  the request stops waiting.
- Fact Check sends up to `8` keys per checkable claim at once (`PRAWDOWID_FACTCHECK_MAX_KEYS`),
  each with one retry and a `15` second deadline ([factcheck.py](../../prawdowid/factcheck.py)).
  The claims:search quota is UNCONFIRMED; a key refused for quota is a failed key.
- A claim cut by the deadline before its sources and judge answered is `not_checked` with
  limitations and the answer stays `ok`. A failed Fact Check (its key for the claim itself, or every
  key), web search (every query) or (for a government claim) gov.pl search does the same when the
  other evidence is not enough; when every checkable claim ends that way because of an outage, the
  answer is a technical notice. A failed key or query among others that answered is only named in a
  limitation. A provider that returns successfully without evidence can lead to
  `insufficient_evidence`. Missing extraction credentials or API failure also produce a technical
  notice, not a factual verdict ([pipeline.py](../../prawdowid/pipeline.py),
  [verifier.py](../../prawdowid/verifier.py)).

Open before a public launch: measure concurrent requests and provider quotas, establish an
operator budget, and test a shared rate limiter across processes. None has a confirmed cost or
capacity figure in this repository.

## Model kosztowy dla pilotażu (po polsku)

Każda liczba poniżej ma źródło: pomiar w tym repozytorium (link do przebiegu) albo cennik (link i
data odczytu). Wartości, których nie zmierzyliśmy, zapisujemy jako wzór z dopiskiem „do uzupełnienia
po pełnym evalu (#16)”. Cenniki odczytaliśmy 22.11.2026. Dolary przeliczamy po kursie średnim NBP
4,0613 zł za 1 USD ([tabela A nr 226/A/NBP/2026 z 20.11.2026](https://api.nbp.pl/api/exchangerates/rates/a/usd/2026-11-20/?format=json)).

## Dla obywatela: 0 zł

- Strona nie wymaga konta ani płatności. Pod polem tekstowym stoi „Bezpłatnie i bez konta.”
  ([frontend/public/index.html](../../frontend/public/index.html)). W API nie ma żadnej ścieżki
  płatności ([prawdowid/app.py](../../prawdowid/app.py)).
- Na Discordzie wystarczy darmowe konto. My nic nie pobieramy.
- SMS i WhatsApp nie są zbudowane. Jeśli powstaną, wpiszemy tu standardowe opłaty operatora, tak jak
  wymaga brief.

## Co zmierzyliśmy

| Pomiar | Wartość | Skąd | Zastrzeżenia |
|---|---|---|---|
| Koszt modeli, sam etap wyodrębniania twierdzeń (Claude Opus 5.5) | 1,82 USD za 100 sprawdzeń, czyli 0,0182 USD za sprawdzenie | [HISTORY.md](../../evals/results/HISTORY.md), wiersz `95e6177`, szybki przebieg, 9 przypadków | Wersja z jednym wywołaniem modelu na sprawdzenie: bez sędziego (#30), bez równoległego sprawdzania twierdzeń (#37) i bez Tavily (#45). Widać to w `git show 95e6177:prawdowid/verifier.py`: „For now one LLM call that finds claims”. |
| Koszt modeli w pełnym potoku, z dowodami z Tavily | 4,27 USD za 100 sprawdzeń, czyli 0,0427 USD za sprawdzenie | [HISTORY.md](../../evals/results/HISTORY.md), wiersz `ca48b84` (pełny przebieg 22.11, 75 przypadków; plik JSON `evals/results/history/20261122T021757.182695Z-ca48b84-full.json` jest w commitach PR #123), pole `cost_per_100_usd` | Średnia z 71 odpowiedzi z ceną; cztery symulowane awarie nie wysyłają zapytań do modelu i są pominięte. To kod z `ca48b84` (`integration/r3`) z #88 (wyodrębnianie na Sonnet 5.5), #95 i #74. Późniejsze zmiany (#106: jeden przebieg wyszukiwania, 2 zapytania modelu na twierdzenie, ustawienia myślenia dla poszczególnych agentów) tego przebiegu nie obejmuje; nowy pełny przebieg go zastąpi. Pole `cost_usd` liczy tylko modele, bez wyszukiwarki (przebiegi mierzono z Tavily). Wcześniejsze pomiary: 4,91 USD za 100 na `edd34a5` (szybki przebieg, 10 przypadków, Opus, przed #95) i 3,96 USD za 100 ze stagingu (README, bez wiersza w HISTORY.md i bez pliku JSON). Pomiar z 21.11 (8 przypadków, bez pliku JSON) dał 5,25 USD za 100. |
| Kredyty Tavily na sprawdzenie | około 4,9 (39 zapytań na 8 przypadków) | [WORKLOG.md](../../WORKLOG.md), wpis z 21.11 o Tavily (#7/#8) | Wyszukiwanie `basic`, 1 kredyt za zapytanie. Lepszego pomiaru nie mamy: [docs/eval-notes.md](../eval-notes.md) i HISTORY.md nie zapisują kredytów. Pomiar sprzed wyszukiwarki gov.pl (#53) i sprzed #106, który zmienił liczbę zapytań (dziś około 4 wyszukiwania na twierdzenie). Pole `cost_usd` w odpowiedzi liczy tylko modele ([prawdowid/verifier.py](../../prawdowid/verifier.py)), więc Tavily doliczamy osobno. |

Pomiar 0,0182 USD pochodzi z innej wersji kodu (jedno wywołanie modelu, Opus) niż pomiar 0,0427 USD,
więc nie wyciągamy z nich podziału kosztu na etapy.

## Ceny

| Pozycja | Cena | Źródło |
|---|---|---|
| Claude Sonnet 5.5, wyodrębnianie twierdzeń (`PRAWDOWID_MODEL`, od #88) i sędzia (`PRAWDOWID_JUDGE_MODEL`) | 2 USD za milion tokenów wejścia, 10 USD za milion tokenów wyjścia | [cennik Anthropic](https://platform.claude.com/docs/en/about-claude/pricing) |
| Claude Opus 5.5, wyodrębnianie twierdzeń w pomiarach sprzed #88 | 4 USD i 20 USD | jak wyżej |
| Claude Haiku 5.5, ranking fragmentów (`PRAWDOWID_RERANK_MODEL`) | 0,10 USD i 0,50 USD przy promptach do 100 tys. tokenów | jak wyżej |
| Tavily | Konto jest na planie Researcher (1000 kredytów miesięcznie za darmo) z opłatą za zużycie (pay as you go): 0,008 USD za kredyt po wyczerpaniu darmowych. Limit konta podniesiono 22.11 do 4000 kredytów miesięcznie; czy wliczają się w to darmowe 1000: UNCONFIRMED. Plany z miesięczną opłatą, których nie używamy: Project 30 USD za 4000 kredytów, Bootstrap 100 USD za 15 000, Startup 220 USD za 38 000, Growth 500 USD za 100 000 (0,005 USD za kredyt, ale tylko przy wykorzystaniu całego planu). Wyszukiwanie `basic` kosztuje 1 kredyt. | [Tavily, API credits](https://docs.tavily.com/documentation/api-credits), odczyt 22.11.2026 |
| Google Fact Check Tools API | Google nie publikuje cennika, wymaga tylko klucza API. Limity zapytań: UNCONFIRMED. | [dokumentacja API](https://developers.google.com/fact-check/tools/api) |
| EUvsDisinfo (serwer MCP) | Osobisty klucz z euvsdisinfo.eu. Cennika nie znaleźliśmy: UNCONFIRMED. | [prawdowid/euvsdisinfo.py](../../prawdowid/euvsdisinfo.py) |
| Wyszukiwarka www.gov.pl | Publiczna wyszukiwarka serwisu, bez klucza. Jej stabilność: UNCONFIRMED. | [docs/sources.md](../sources.md) |
| Embeddingi e5-large (osobny indeks pgvector; sprawdzanie używa BM25 w pamięci, bez embeddingów) | Liczone na naszym serwerze, bez opłaty za zapytanie | [WORKLOG.md](../../WORKLOG.md), decyzja z 21.11 |
| Serwer OVHcloud VPS-2 (4 vCPU, 8 GB RAM, 75 GB NVMe) | od 30,77 zł netto, czyli 37,85 zł brutto miesięcznie | [cennik VPS OVHcloud](https://www.ovhcloud.com/pl/vps/) |
| Domena .pl w OVHcloud | 6,99 zł za pierwszy rok (promocja), 58,99 zł za każde odnowienie. Cennik nie mówi, czy to netto, czy brutto. | [cennik domen OVHcloud](https://www.ovhcloud.com/pl/domains/tld/) |
| Bot Discord | Może działać jako proces na tym samym VPS (profil `discord` w [compose.yaml](../../compose.yaml)). Na produkcji jeszcze go nie uruchomiliśmy (#59). Dokumentacja Discorda nie podaje opłat za API botów. | [Discord, Bots](https://docs.discord.com/developers/bots/overview) |

Cennik VPS podaje cenę „od”. Kwotę z faktury OVHcloud wpisuje zespół.

## Jedno sprawdzenie i 1000 sprawdzeń

```text
koszt sprawdzenia = koszt modeli + kredyty Tavily × cena kredytu
                    (Google Fact Check, gov.pl, korpus i embeddingi: 0 zł za zapytanie, EUvsDisinfo: UNCONFIRMED)

koszt modeli (pełny przebieg na ca48b84)   = 0,0427 USD
Tavily, kredyt płatny        = 4,875 × 0,008 = 0,0390 USD
jedno sprawdzenie (po wyczerpaniu darmowych kredytów) = 0,0817 USD, czyli 0,33 zł

1000 sprawdzeń:
  modele                     = 42,70 USD
  kredyty Tavily             = 4875, z czego 1000 darmowych, 3875 × 0,008 = 31,00 USD
  razem                      = 73,70 USD, czyli 299 zł
  bez darmowych kredytów     = 81,70 USD, czyli 332 zł (gdy darmowe 1000 zużyją testy)
```

Plan Growth (500 USD miesięcznie) nie obniża tej kwoty: przy 1000 sprawdzeń kredyty z abonamentu
kosztowałyby 500 USD, a po stawce za zużycie 31 USD. Stawka 0,005 USD za kredyt jest osiągalna
dopiero wtedy, gdy zużywamy cały plan, czyli około 100 000 kredytów, tak jak przy około 20 500
sprawdzeniach miesięcznie. Przy 1000 sprawdzeń jest to więc koszt krańcowy, a nie rachunek.

Limit konta (4000 kredytów) starcza na 820 do 1025 sprawdzeń miesięcznie. Dolna granica to 4000 ÷ 4,875 i
zakłada, że limit obejmuje darmowe 1000 kredytów. Górna to (1000 + 4000) ÷ 4,875 i zakłada, że limit
dotyczy tylko kredytów płatnych. Odczyt z 22.11 około 1:40 (plan 2281 z 1500, płatne 778 z 1000, API
odmówiło z powodem „pay-as-you-go limit”) wskazuje na to drugie, ale rozstrzygnie to odczyt
`GET https://api.tavily.com/usage` (pola `plan_limit`, `paygo_limit`, `paygo_usage`): UNCONFIRMED.
Ten sam odczyt podaje w planie 1500 kredytów, a nie 1000 z publicznego cennika: UNCONFIRMED. Przy 1500
wolnych kredytów 1000 sprawdzeń kosztuje 69,70 USD, czyli 283 zł. Gdy limit się kończy, API odmawia, a
kod traktuje odmowę jak każdą awarię wyszukiwarki (patrz niżej).

Powtórzone zapytania do wyszukiwarki nie kosztują kredytów przez 24 godziny (#110,
[prawdowid/search_cache.py](../../prawdowid/search_cache.py)); wyniki są też zapisywane na dysku. Klucz
to zapytanie, które pisze model, a nie pytanie użytkownika. To samo pytanie w ciągu 30 minut wraca z
pamięci wyników całych odpowiedzi ([prawdowid/app.py](../../prawdowid/app.py)), a po 30 minutach model
może napisać inne zapytania i wydać kredyty. Ile kredytów to oszczędza w rzeczywistym ruchu, nie
zmierzyliśmy, więc rachunek wyżej zakłada, że nikt nie powtarza pytań.

Przy stawce 0,008 USD modele to 52% kosztu sprawdzenia, a Tavily 48%. Koszt modeli pochodzi z pełnego
przebiegu na 75 przypadkach, a liczba kredytów Tavily z wcześniejszego przebiegu na 8 przypadkach, więc
to wciąż orientacja. Kredyty Tavily z pełnego przebiegu policzymy tak:

```text
do uzupełnienia dla kredytów Tavily (#16):
K_modele = cost_per_100_usd / 100           wiersz HISTORY.md dla commitu zgłoszenia (ca48b84: 0,0427 USD)
N_Tavily = kredyty zużyte w tym przebiegu / liczba sprawdzeń
           (z odpowiedzi Tavily z `include_usage=True`, z `GET /usage` albo z licznika
           `search_cache.track()`; nie z panelu, który się spóźnia)
K_1000   = 1000 × K_modele + max(0, 1000 × N_Tavily − 1000) × 0,008 USD
```

Koszt 100 testów, o który pyta jury, to 4,27 USD za modele (pełny przebieg na `ca48b84`, wiersz w
HISTORY.md z plikiem JSON `evals/results/history/20261122T021757.182695Z-ca48b84-full.json`, oba w commitach PR #123) plus
około 3,90 USD za Tavily (szacunek: średnio około 4,9 kredytu na sprawdzenie × 100 × 0,008 USD, bez darmowych kredytów;
przy górnej granicy 12 kredytów na sprawdzenie byłoby to 9,60 USD). Wiersz `95e6177`
(1,82 USD za 100) to wersja z jednym wywołaniem modelu, bez sędziego i bez Tavily.

## Koszt stały miesięcznie

| Pozycja | Miesięcznie |
|---|---|
| VPS-2 | 37,85 zł brutto (cena „od” z cennika) |
| Domena faktczyfejk.pl | 4,92 zł (58,99 zł rocznie przy odnowieniu) |
| Bot Discord, po uruchomieniu (#59) | 0 zł ponad VPS |
| Razem | około 42,77 zł |

Na tym samym serwerze działa też inny projekt, doc2json.pl ([docs/deploy.md](../deploy.md)). Cały
koszt VPS przypisany faktczyfejk.pl to więc górna granica.

## 10 razy i 100 razy więcej ruchu

Ruchu produkcyjnego nie mierzyliśmy. Za punkt wyjścia bierzemy umowne 1000 sprawdzeń miesięcznie i
to jest założenie do rachunku, nie prognoza. Tavily liczymy tak, jak konto jest rozliczane: po 0,008 USD za kredyt, po odjęciu 1000
darmowych kredytów. Modele liczymy po 0,0427 USD za sprawdzenie (pełny przebieg na `ca48b84`). Wiersze 1000, 10 000 i
100 000 to szacunki: ten jeden pomiar razy liczba sprawdzeń.

| Sprawdzeń w miesiącu | Modele | Tavily | Stałe | Razem | Udział kosztów stałych |
|---|---|---|---|---|---|
| 1000 | 42,70 USD (173 zł) | 3875 płatnych kredytów, 31,00 USD (126 zł) | 42,77 zł | około 342 zł | 13% |
| 10 000 | 427 USD (1734 zł) | 47 750 płatnych kredytów, 382 USD (1551 zł) | 42,77 zł | około 3328 zł | 1,3% |
| 100 000 | 4270 USD (17 342 zł) | 486 500 płatnych kredytów, 3892 USD (15 807 zł) | 42,77 zł i kolejne serwery, do uzupełnienia (#88) | około 33 191 zł plus serwery | 0,1% bez kolejnych serwerów |

Limit konta Tavily (4000 kredytów) starcza na pierwszy wiersz tylko przy wąskim odczycie (do 1025
sprawdzeń, patrz wyżej), a na dwa pozostałe nie starcza w żadnym. Przy większym ruchu trzeba go podnieść
albo przejść na plan z abonamentem.

Co z tego wynika:

- Przy 10 i 100 razy większym ruchu liczą się już tylko koszty zmienne. Serwer i domena to poniżej
  2% rachunku.
- Z kosztów zmiennych od 52 do 58% to tokeny modeli, reszta to kredyty wyszukiwarki. Przy 100 razy
  większym ruchu Tavily potrzebuje prawie 490 tys. kredytów miesięcznie, a największy plan z cennika
  ma 100 tys. Cena dla takiej skali: do negocjacji, UNCONFIRMED. Z cennika wychodzi, że plany
  z abonamentem wyjdą taniej niż opłata za zużycie dopiero przy dużym ruchu: Startup (220 USD za
  38 000 kredytów) plus 10 750 kredytów po 0,008 USD to 306 USD zamiast 382 USD przy 10 000
  sprawdzeń, a Growth plus 387 500 kredytów po 0,008 USD to 3600 USD zamiast 3892 USD przy 100 000.
  Przy 1000 sprawdzeń abonament się nie opłaca.
- Koszt modeli dzieli się na trzy etapy: wyodrębnianie
  ([prawdowid/verifier.py](../../prawdowid/verifier.py)), ranking na Haiku 5.5
  ([prawdowid/rerank.py](../../prawdowid/rerank.py)) i sędzia na Sonnet 5.5
  ([prawdowid/judge.py](../../prawdowid/judge.py)). Pomiar 0,0182 USD za samo wyodrębnianie
  pochodzi z wersji na Opus 5.5 z jednym wywołaniem modelu. Od #88 (`83d6c65`) wyodrębnianie domyślnie
  idzie na Sonnet 5.5, a pomiar 0,0427 USD z `ca48b84` obejmuje już ten kod, #95 i #74, ale nie #106. Jak koszt
  dzieli się między wyodrębnianie, ranking i sędziego, nie zmierzyliśmy. Dziennik sprawdzeń zapisuje każde wywołanie modelu z
  tokenami, więc podział wyjdzie z pełnego przebiegu (#16).
- Kredyty zależą od liczby zapytań na twierdzenie (`PRAWDOWID_QUERIES_PER_CLAIM`, domyślnie 2). Do
  tego dochodzi wyszukiwanie z treścią twierdzenia i jedno wyszukiwanie tylko w serwisach
  weryfikujących, w tym samym przebiegu, czyli około 4 wyszukiwań na twierdzenie bez ponawiania.
  Każde zapytanie mniej to jeden kredyt mniej na każde sprawdzane twierdzenie. Wpływ na jakość: do
  zmierzenia. Wyszukiwanie w korpusie działa w pamięci naszego serwera i nie kosztuje nic za
  zapytanie. Jest podpięte do każdego sprawdzenia ([corpus.md](../corpus.md)), ale jego wpływu na
  liczbę zapytań do Tavily nie mierzyliśmy.

## Skalowanie

Obciążenie, limity i zachowanie przy awariach opisuje część angielska wyżej. Serwer jest jeden i nie ma
zapasowego ([docs/deploy.md](../deploy.md), sekcja „Known limits”). Alertu o kończących się kredytach
Tavily nie ma (#75).

Przy większym ruchu potrzebne będą kolejne procesy albo serwery i wspólny licznik limitu dla nich
wszystkich. Ile, wyjdzie z testu obciążeniowego:

```text
do uzupełnienia (#88):
liczba procesów = szczytowa liczba sprawdzeń na minutę / przepustowość jednego procesu
```
