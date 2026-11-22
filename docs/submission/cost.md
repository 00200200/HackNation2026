# Koszt i zachowanie pod obciążeniem

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
| Koszt modeli w pełnym potoku, z dowodami z Tavily | 4,27 USD za 100 sprawdzeń, czyli 0,0427 USD za sprawdzenie | [HISTORY.md](../../evals/results/HISTORY.md), wiersz `ca48b84` (pełny przebieg 22.11, 75 przypadków; plik JSON `evals/results/history/20261122T021757.182695Z-ca48b84-full.json` jest w commitach PR #123), pole `cost_per_100_usd` | Średnia z 71 odpowiedzi z ceną. Runner na `integration/r3` pomija każdy przypadek z `simulate` (cztery przypadki J). Tylko trzy z nich (`llm_unavailable`) nic nie kosztują; J01 (symulowana awaria Fact Check) wołał modele i kosztował 0,0730 USD, więc z nim średnia wynosi około 4,31 USD za 100, a nie 4,27. To kod `integration/r3` z #88 (wyodrębnianie na Sonnet 5.5), #95 i #74, czyli ten, który ma zostać wdrożony. Pole `cost_usd` liczy tylko modele, bez Tavily. Wcześniejsze pomiary: 4,91 USD za 100 na `edd34a5` (szybki przebieg, 10 przypadków, Opus, przed #95) i 3,96 USD za 100 ze stagingu (README, bez wiersza w HISTORY.md i bez pliku JSON). Pomiar z 21.11 (8 przypadków, bez pliku JSON) dał 5,25 USD za 100. |
| Kredyty Tavily na sprawdzenie | około 4,9 (39 zapytań na 8 przypadków) | [WORKLOG.md](../../WORKLOG.md), wpis z 21.11 o Tavily (#7/#8) | Wyszukiwanie `basic`, 1 kredyt za zapytanie. Lepszego pomiaru nie mamy: [docs/eval-notes.md](../eval-notes.md) i HISTORY.md nie zapisują kredytów. Pomiar sprzed wyszukiwarki gov.pl (#53). Pole `cost_usd` w odpowiedzi liczy tylko modele ([prawdowid/verifier.py](../../prawdowid/verifier.py)), więc Tavily doliczamy osobno. |

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
[prawdowid/search_cache.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/search_cache.py)); wyniki są też zapisywane na dysku. Klucz
to zapytanie, które pisze model, a nie pytanie użytkownika. To samo pytanie w ciągu 30 minut wraca z
pamięci wyników całych odpowiedzi ([prawdowid/app.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/app.py#L80)), a po 30 minutach model
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
  ([prawdowid/verifier.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/verifier.py#L45)), ranking na Haiku 5.5
  ([prawdowid/rerank.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/rerank.py#L50)) i sędzia na Sonnet 5.5
  ([prawdowid/judge.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/judge.py#L64)). Pomiar 0,0182 USD za samo wyodrębnianie
  pochodzi z wersji na Opus 5.5 z jednym wywołaniem modelu. Od #88 (`83d6c65`) wyodrębnianie domyślnie
  idzie na Sonnet 5.5, a pomiar 0,0427 USD z `ca48b84` obejmuje już ten kod, #95 i #74. Jak koszt
  dzieli się między wyodrębnianie, ranking i sędziego, nie zmierzyliśmy. Dziennik sprawdzeń zapisuje każde wywołanie modelu z
  tokenami, więc podział wyjdzie z pełnego przebiegu (#16).
- Kredyty zależą od liczby zapytań na twierdzenie (`PRAWDOWID_QUERIES_PER_CLAIM`, domyślnie 3). Każde
  zapytanie mniej to jeden kredyt mniej na każde sprawdzane twierdzenie. Wpływ na jakość: do
  zmierzenia. Wyszukiwanie w korpusie działa w pamięci naszego serwera i nie kosztuje nic za
  zapytanie. W buildzie `integration/r3` jest podpięte do sprawdzania (#74), ale jego wpływu na
  liczbę zapytań do Tavily nie mierzyliśmy.

## Zachowanie pod obciążeniem

Zmierzyliśmy tylko medianę czasu odpowiedzi ([HISTORY.md](../../evals/results/HISTORY.md)): 3,9 s w
szybkim przebiegu na `95e6177` (wersja z jednym wywołaniem modelu) i 18,2 s w pełnym przebiegu na
`8c6f396`, który zniekształciły timeouty Anthropic i zbyt ciasny budżet czasu
([docs/eval-notes.md](../eval-notes.md)). Pełny przebieg na `ca48b84` (75
przypadków, wiersz w HISTORY.md) dał 17,8 s. Wcześniej szybki przebieg na `edd34a5` (10 przypadków) dał 24,9 s. Próg z briefu to 30 s. Nie mierzyliśmy, ile sprawdzeń naraz
wytrzyma serwer, czasu p95, punktu nasycenia ani kosztu pod obciążeniem. Test obciążeniowy z
podmienionymi źródłami to #88.

Ustawienia w kodzie buildu `integration/r3` (`235209b`), który ma zostać wdrożony po scaleniu do `main`. To
konfiguracja, nie zmierzona przepustowość:

- Backend to jeden proces uvicorn ([Dockerfile](../../Dockerfile)). Limit 10 sprawdzeń na minutę z
  jednego adresu IP jest trzymany w pamięci tego procesu ([prawdowid/app.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/app.py#L43)).
  Wszyscy użytkownicy Discorda dzielą adres IP bota, więc i limit (#59).
- API kończy czekanie po 60 s, a całe sprawdzenie ma budżet 40 s
  ([prawdowid/pipeline.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/pipeline.py#L55)). Google Fact Check ma 15 s, EUvsDisinfo
  5 s w potoku, korpus 5 s, jedno zapytanie do wyszukiwarki 10 s, pobranie strony 8 s.
- Jedno sprawdzenie bada najwyżej 3 twierdzenia i wysyła po 3 zapytania na twierdzenie
  ([prawdowid/verifier.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/verifier.py#L166-L168)), a gdy dowodów nie starcza i zostaje co
  najmniej 18 s, jedno ponowne wyszukiwanie z treścią twierdzenia
  ([prawdowid/pipeline.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/pipeline.py#L144-L151)). Jedno sprawdzenie może więc zużyć do
  12 kredytów Tavily (3 twierdzenia × 4 wyszukiwania). Nie ma globalnej kolejki ani limitu wydatków.
- Serwer jest jeden i nie ma zapasowego ([docs/deploy.md](../deploy.md), sekcja „Known limits”).

Co widzi użytkownik, kiedy coś się kończy: jedenaste sprawdzenie w ciągu minuty dostaje HTTP 429 z
komunikatem po polsku. Brak klucza do modelu albo jego awaria daje komunikat techniczny. Gdy padną
wszystkie źródła twierdzenia, nie odpowie sędzia albo skończy się czas, twierdzenie dostaje „nie
sprawdzono” z powodem. Od #60 (w `integration/r3`) tak samo kończy się awaria źródła, które może
rozstrzygnąć werdykt (Fact Check albo wyszukiwarka), gdy dowodów nie starcza: wynik nie brzmi już
„brak wystarczających dowodów” ([prawdowid/pipeline.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/pipeline.py#L177-L193)). Dotyczy
to też wyczerpania kredytów Tavily, bo dla kodu to zwykła awaria wyszukiwarki
([prawdowid/websearch.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/websearch.py#L163), [prawdowid/search_cache.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/search_cache.py#L201-L220)). Korpus, jako plik na naszym dysku, nie
liczy się jako źródło, które odpowiedziało. Do czasu scalenia `integration/r3` ten sam przypadek na
`main` daje jeszcze „brak wystarczających dowodów” z dopiskiem o awarii. Alertu o kończących się
kredytach nie ma (#75).

Przy większym ruchu potrzebne będą kolejne procesy albo serwery i wspólny licznik limitu dla nich
wszystkich. Ile, wyjdzie z testu obciążeniowego:

```text
do uzupełnienia (#88):
liczba procesów = szczytowa liczba sprawdzeń na minutę / przepustowość jednego procesu
```
