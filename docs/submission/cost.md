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
| Koszt modeli w pełnym potoku, z dowodami z Tavily | 5,25 USD za 100 sprawdzeń, czyli 0,0525 USD za sprawdzenie | [WORKLOG.md](../../WORKLOG.md), wpis z 21.11 o Tavily (#7/#8), 8 przypadków | Jeden przebieg, w którym każde sprawdzenie zmieściło się w budżecie 25 s. Nie ma do niego pliku JSON. Pomiar sprzed wyszukiwarki gov.pl (#53). |
| Kredyty Tavily na sprawdzenie | około 4,9 (39 zapytań na 8 przypadków) | ten sam wpis w [WORKLOG.md](../../WORKLOG.md) | Wyszukiwanie `basic`, 1 kredyt za zapytanie. Pole `cost_usd` w odpowiedzi liczy tylko modele ([prawdowid/verifier.py](../../prawdowid/verifier.py)), więc Tavily doliczamy osobno. |

Według tych pomiarów samo wyodrębnianie to około jednej trzeciej kosztu modeli (0,0182 z 0,0525
USD). Oba pomiary pochodzą z różnych wersji kodu, więc to tylko rząd wielkości.

## Ceny

| Pozycja | Cena | Źródło |
|---|---|---|
| Claude Opus 5.5, wyodrębnianie twierdzeń (`PRAWDOWID_MODEL`) | 4 USD za milion tokenów wejścia, 20 USD za milion tokenów wyjścia | [cennik Anthropic](https://platform.claude.com/docs/en/about-claude/pricing) |
| Claude Sonnet 5.5, sędzia (`PRAWDOWID_JUDGE_MODEL`) | 2 USD i 10 USD | jak wyżej |
| Claude Haiku 5.5, ranking fragmentów (`PRAWDOWID_RERANK_MODEL`) | 0,10 USD i 0,50 USD przy promptach do 100 tys. tokenów | jak wyżej |
| Tavily | 1000 kredytów miesięcznie za darmo, potem 0,008 USD za kredyt. Plany: 30 USD za 4000 kredytów, 100 USD za 15 000, 220 USD za 38 000, 500 USD za 100 000 (0,005 USD za kredyt). Wyszukiwanie `basic` kosztuje 1 kredyt. | [Tavily, API credits](https://docs.tavily.com/documentation/api-credits) |
| Google Fact Check Tools API | Google nie publikuje cennika, wymaga tylko klucza API. Limity zapytań: UNCONFIRMED. | [dokumentacja API](https://developers.google.com/fact-check/tools/api) |
| EUvsDisinfo (serwer MCP) | Osobisty klucz z euvsdisinfo.eu. Cennika nie znaleźliśmy: UNCONFIRMED. | [prawdowid/euvsdisinfo.py](../../prawdowid/euvsdisinfo.py) |
| Wyszukiwarka www.gov.pl | Publiczna wyszukiwarka serwisu, bez klucza. Jej stabilność: UNCONFIRMED. | [docs/sources.md](../sources.md) |
| Embeddingi korpusu (e5-large) | Liczone na naszym serwerze, bez opłaty za zapytanie | [WORKLOG.md](../../WORKLOG.md), decyzja z 21.11 |
| Serwer OVHcloud VPS-2 (4 vCPU, 8 GB RAM, 75 GB NVMe) | od 30,77 zł netto, czyli 37,85 zł brutto miesięcznie | [cennik VPS OVHcloud](https://www.ovhcloud.com/pl/vps/) |
| Domena .pl w OVHcloud | 6,99 zł za pierwszy rok (promocja), 58,99 zł za każde odnowienie. Cennik nie mówi, czy to netto, czy brutto. | [cennik domen OVHcloud](https://www.ovhcloud.com/pl/domains/tld/) |
| Bot Discord | Może działać jako proces na tym samym VPS (profil `discord` w [compose.yaml](../../compose.yaml)). Na produkcji jeszcze go nie uruchomiliśmy (#59). Dokumentacja Discorda nie podaje opłat za API botów. | [Discord, Bots](https://docs.discord.com/developers/bots/overview) |

Cennik VPS podaje cenę „od”. Kwotę z faktury OVHcloud wpisuje zespół.

## Jedno sprawdzenie i 1000 sprawdzeń

```text
koszt sprawdzenia = koszt modeli + kredyty Tavily × cena kredytu
                    (Google Fact Check, gov.pl i embeddingi: 0 zł za zapytanie, EUvsDisinfo: UNCONFIRMED)

koszt modeli                 = 0,0525 USD
Tavily po 0,008 USD          = 4,875 × 0,008 = 0,0390 USD
Tavily po 0,005 USD (Growth) = 4,875 × 0,005 = 0,0244 USD

jedno sprawdzenie  = od 0,0769 do 0,0915 USD, czyli od 0,31 do 0,37 zł
1000 sprawdzeń     = od 76,88 do 91,50 USD, czyli od 312 do 372 zł
```

Przy stawce 0,008 USD modele to 57% tej kwoty, a Tavily 43%. Te liczby to orientacja z jednego
przebiegu na 8 przypadkach. Ostateczne wartości policzymy z pełnego przebiegu:

```text
do uzupełnienia po pełnym evalu (#16):
K_modele = cost_per_100_usd / 100           wiersz HISTORY.md dla commitu zgłoszenia
N_Tavily = kredyty zużyte w tym przebiegu / liczba sprawdzeń
           (stan licznika w panelu Tavily przed przebiegiem i po nim)
K_1000   = 1000 × (K_modele + N_Tavily × cena kredytu)
```

Koszt 100 testów, o który pyta jury, wynosi w [HISTORY.md](../../evals/results/HISTORY.md) 1,82 USD
(`95e6177`, jedyny wiersz z tym polem oparty na pliku JSON). Wiersz odtworzony z pamięci, sprzed
Tavily, podaje 1,65 USD. Żaden z nich nie obejmuje kredytów Tavily ani obecnego potoku.

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
to jest założenie do rachunku, nie prognoza. Tavily liczymy po 0,008 USD za kredyt, po odjęciu 1000
darmowych kredytów.

| Sprawdzeń w miesiącu | Modele | Tavily | Stałe | Razem | Udział kosztów stałych |
|---|---|---|---|---|---|
| 1000 | 52,50 USD (213 zł) | 3875 kredytów, 31,00 USD (126 zł) | 42,77 zł | około 382 zł | 11% |
| 10 000 | 525 USD (2132 zł) | 47 750 kredytów, 382 USD (1551 zł) | 42,77 zł | około 3726 zł | 1,1% |
| 100 000 | 5250 USD (21 322 zł) | 486 500 kredytów, 3892 USD (15 807 zł) | 42,77 zł i kolejne serwery, do uzupełnienia (#88) | około 37 171 zł plus serwery | 0,1% bez kolejnych serwerów |

Co z tego wynika:

- Przy 10 i 100 razy większym ruchu liczą się już tylko koszty zmienne. Serwer i domena to poniżej
  2% rachunku.
- Z kosztów zmiennych od 57 do 63% to tokeny modeli, reszta to kredyty wyszukiwarki. Przy 100 razy
  większym ruchu Tavily potrzebuje prawie 490 tys. kredytów miesięcznie, a największy plan z cennika
  ma 100 tys. Cena dla takiej skali: do negocjacji, UNCONFIRMED. Po stawce planu Growth (0,005 USD)
  byłoby to 2437,50 USD (9899 zł).
- Koszt modeli dzieli się na trzy etapy. Wyodrębnianie robi Opus 5.5
  ([prawdowid/verifier.py](../../prawdowid/verifier.py#L43)) i według pomiarów wyżej to około
  jednej trzeciej kosztu modeli (0,0182 z 0,0525 USD). Resztę, około dwóch trzecich, biorą ranking
  na Haiku 5.5 ([prawdowid/rerank.py](../../prawdowid/rerank.py#L49)) i sędzia na Sonnet 5.5
  ([prawdowid/judge.py](../../prawdowid/judge.py#L62)). Token
  Sonnet kosztuje połowę tego co Opus, więc przejście wyodrębniania na Sonnet przy tej samej liczbie
  tokenów obetnie koszt modeli o około 17%, nie o połowę. Jak koszt dzieli się między ranking i
  sędziego, nie zmierzyliśmy. Dziennik sprawdzeń zapisuje każde wywołanie modelu z tokenami, więc
  podział wyjdzie z pełnego przebiegu (#16). Czy jakość utrzyma się po zmianie modelu, sprawdza #88,
  i bez tego pomiaru domyślnych modeli nie zmieniamy.
- Kredyty zależą od liczby zapytań na twierdzenie (`PRAWDOWID_QUERIES_PER_CLAIM`, domyślnie 3). Każde
  zapytanie mniej to jeden kredyt mniej na każde sprawdzane twierdzenie. Wpływ na jakość: do
  zmierzenia. Wyszukiwanie w korpusie działa na naszym serwerze i nie kosztuje nic za zapytanie, ale
  jeszcze nie jest podpięte (#74).

## Zachowanie pod obciążeniem

Zmierzyliśmy tylko medianę czasu odpowiedzi ([HISTORY.md](../../evals/results/HISTORY.md)): 3,9 s w
szybkim przebiegu na `95e6177` (wersja z jednym wywołaniem modelu) i 18,2 s w pełnym przebiegu na
`8c6f396`, który zniekształciły timeouty Anthropic i zbyt ciasny budżet czasu
([docs/eval-notes.md](../eval-notes.md)). Próg z briefu to 30 s. Nie mierzyliśmy, ile sprawdzeń naraz
wytrzyma serwer, czasu p95, punktu nasycenia ani kosztu pod obciążeniem. Test obciążeniowy z
podmienionymi źródłami to #88.

Ustawienia w kodzie na `main` (`1aa173f`). To konfiguracja, nie zmierzona przepustowość, a PR #109
zmienia część z nich (budżet 40 s, najwyżej 3 twierdzenia):

- Backend to jeden proces uvicorn ([Dockerfile](../../Dockerfile)). Limit 10 sprawdzeń na minutę z
  jednego adresu IP jest trzymany w pamięci tego procesu ([prawdowid/app.py](../../prawdowid/app.py#L30)).
  Wszyscy użytkownicy Discorda dzielą adres IP bota, więc i limit (#59).
- API kończy czekanie po 60 s, a całe sprawdzenie ma budżet 25 s
  ([prawdowid/pipeline.py](../../prawdowid/pipeline.py#L35)). Google Fact Check ma 15 s, EUvsDisinfo
  5 s w potoku, jedno zapytanie do wyszukiwarki 10 s, pobranie strony 8 s.
- Jedno sprawdzenie bada najwyżej 5 twierdzeń i wysyła po 3 zapytania na twierdzenie
  ([prawdowid/verifier.py](../../prawdowid/verifier.py)). Nie ma globalnej kolejki ani limitu wydatków.
- Serwer jest jeden i nie ma zapasowego ([docs/deploy.md](../deploy.md), sekcja „Known limits”).

Co widzi użytkownik, kiedy coś się kończy: jedenaste sprawdzenie w ciągu minuty dostaje HTTP 429 z
komunikatem po polsku. Brak klucza do modelu albo jego awaria daje komunikat techniczny. Gdy padną
wszystkie źródła twierdzenia, nie odpowie sędzia albo skończy się czas, twierdzenie dostaje „nie
sprawdzono” z powodem. Gdy padnie tylko część źródeł, a reszta nic nie znajdzie, wynik brzmi dziś
„brak wystarczających dowodów”, a w ograniczeniach stoi, które źródło nie odpowiedziało
([prawdowid/pipeline.py](../../prawdowid/pipeline.py#L137)). Tak skończy się też wyczerpanie
kredytów Tavily, gdy Google Fact Check i gov.pl nic nie znajdą: dla kodu to zwykła awaria
wyszukiwarki ([prawdowid/websearch.py](../../prawdowid/websearch.py#L113)). To luka #60, a poprawka
czeka w PR #109. Alertu o kończących się kredytach nie ma (#75).

Przy większym ruchu potrzebne będą kolejne procesy albo serwery i wspólny licznik limitu dla nich
wszystkich. Ile, wyjdzie z testu obciążeniowego:

```text
do uzupełnienia (#88):
liczba procesów = szczytowa liczba sprawdzeń na minutę / przepustowość jednego procesu
```
