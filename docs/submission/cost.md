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
| Koszt modeli w pełnym potoku, z dowodami z Tavily | 4,91 USD za 100 sprawdzeń, czyli 0,0491 USD za sprawdzenie | [HISTORY.md](../../evals/results/HISTORY.md) na `integration/r3`, wiersz `edd34a5`, szybki przebieg, 10 przypadków | Kod `integration/r2`, jeszcze bez wyszukiwania z #95 i z wyodrębnianiem na Opus 5.5. Obecny kod wyodrębnia na Sonnet 5.5 (#88), a tego nie mierzyliśmy, więc 0,0491 USD to górna granica. Wiersz trafi na `main` ze scaleniem `integration/r3`. Wcześniejszy pomiar z 21.11 (8 przypadków, bez pliku JSON) dał 5,25 USD za 100. |
| Kredyty Tavily na sprawdzenie | około 4,9 (39 zapytań na 8 przypadków) | [WORKLOG.md](../../WORKLOG.md), wpis z 21.11 o Tavily (#7/#8) | Wyszukiwanie `basic`, 1 kredyt za zapytanie. Lepszego pomiaru nie mamy: [docs/eval-notes.md](../eval-notes.md) i HISTORY.md nie zapisują kredytów. Pomiar sprzed wyszukiwarki gov.pl (#53). Pole `cost_usd` w odpowiedzi liczy tylko modele ([prawdowid/verifier.py](../../prawdowid/verifier.py)), więc Tavily doliczamy osobno. |

Według pomiarów samo wyodrębnianie na Opusie to około jednej trzeciej kosztu modeli (0,0182 z
0,0491 USD). Pomiary pochodzą z różnych wersji kodu, więc to tylko rząd wielkości.

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
| Embeddingi korpusu (e5-large) | Liczone na naszym serwerze, bez opłaty za zapytanie | [WORKLOG.md](../../WORKLOG.md), decyzja z 21.11 |
| Serwer OVHcloud VPS-2 (4 vCPU, 8 GB RAM, 75 GB NVMe) | od 30,77 zł netto, czyli 37,85 zł brutto miesięcznie | [cennik VPS OVHcloud](https://www.ovhcloud.com/pl/vps/) |
| Domena .pl w OVHcloud | 6,99 zł za pierwszy rok (promocja), 58,99 zł za każde odnowienie. Cennik nie mówi, czy to netto, czy brutto. | [cennik domen OVHcloud](https://www.ovhcloud.com/pl/domains/tld/) |
| Bot Discord | Może działać jako proces na tym samym VPS (profil `discord` w [compose.yaml](../../compose.yaml)). Na produkcji jeszcze go nie uruchomiliśmy (#59). Dokumentacja Discorda nie podaje opłat za API botów. | [Discord, Bots](https://docs.discord.com/developers/bots/overview) |

Cennik VPS podaje cenę „od”. Kwotę z faktury OVHcloud wpisuje zespół.

## Jedno sprawdzenie i 1000 sprawdzeń

```text
koszt sprawdzenia = koszt modeli + kredyty Tavily × cena kredytu
                    (Google Fact Check, gov.pl, korpus i embeddingi: 0 zł za zapytanie, EUvsDisinfo: UNCONFIRMED)

koszt modeli (górna granica) = 0,0491 USD
Tavily, kredyt płatny        = 4,875 × 0,008 = 0,0390 USD
jedno sprawdzenie (po wyczerpaniu darmowych kredytów) = 0,0881 USD, czyli 0,36 zł

1000 sprawdzeń:
  modele                     = 49,10 USD
  kredyty Tavily             = 4875, z czego 1000 darmowych, 3875 × 0,008 = 31,00 USD
  razem                      = 80,10 USD, czyli 325 zł
  bez darmowych kredytów     = 88,10 USD, czyli 358 zł (gdy darmowe 1000 zużyją testy)
```

Plan Growth (500 USD miesięcznie) nie obniża tej kwoty: przy 1000 sprawdzeń kredyty z abonamentu
kosztowałyby 500 USD, a po stawce za zużycie 31 USD. Stawka 0,005 USD za kredyt jest osiągalna
dopiero wtedy, gdy zużywamy cały plan, czyli około 100 000 kredytów, tak jak przy około 20 500
sprawdzeniach miesięcznie. Przy 1000 sprawdzeń jest to więc koszt krańcowy, a nie rachunek.

Limit konta (4000 kredytów) starcza na około 820 sprawdzeń miesięcznie (4000 ÷ 4,875). Żeby obsłużyć
1000, trzeba go podnieść. Czy po wyczerpaniu limitu Tavily odmawia, czy dalej nalicza, nie
sprawdziliśmy: UNCONFIRMED. Kod traktuje odmowę jak każdą awarię wyszukiwarki (patrz niżej).

Powtórzone pytania nie kosztują kredytów: wyniki Tavily są w pamięci przez 24 godziny (#110,
[prawdowid/search_cache.py](../../prawdowid/search_cache.py)). Ile kredytów to oszczędza w
rzeczywistym ruchu, nie zmierzyliśmy, więc rachunek wyżej zakłada, że nikt nie powtarza pytań.

Przy stawce 0,008 USD modele to 56% kosztu sprawdzenia, a Tavily 44%. Te liczby to orientacja z
dwóch przebiegów na 8 i 10 przypadkach. Ostateczne wartości policzymy z pełnego przebiegu:

```text
do uzupełnienia po pełnym evalu (#16):
K_modele = cost_per_100_usd / 100           wiersz HISTORY.md dla commitu zgłoszenia
N_Tavily = kredyty zużyte w tym przebiegu / liczba sprawdzeń
           (stan licznika w panelu Tavily przed przebiegiem i po nim)
K_1000   = 1000 × K_modele + max(0, 1000 × N_Tavily − 1000) × 0,008 USD
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
to jest założenie do rachunku, nie prognoza. Tavily liczymy tak, jak konto jest rozliczane: po 0,008 USD za kredyt, po odjęciu 1000
darmowych kredytów. Modele liczymy po 0,0491 USD za sprawdzenie (górna granica).

| Sprawdzeń w miesiącu | Modele | Tavily | Stałe | Razem | Udział kosztów stałych |
|---|---|---|---|---|---|
| 1000 | 49,10 USD (199 zł) | 3875 płatnych kredytów, 31,00 USD (126 zł) | 42,77 zł | około 368 zł | 12% |
| 10 000 | 491 USD (1994 zł) | 47 750 płatnych kredytów, 382 USD (1551 zł) | 42,77 zł | około 3588 zł | 1,2% |
| 100 000 | 4910 USD (19 941 zł) | 486 500 płatnych kredytów, 3892 USD (15 807 zł) | 42,77 zł i kolejne serwery, do uzupełnienia (#88) | około 35 791 zł plus serwery | 0,1% bez kolejnych serwerów |

Limit konta Tavily (4000 kredytów) nie starcza już na pierwszy wiersz. Przy każdym z trzech
wolumenów trzeba go podnieść albo przejść na plan z abonamentem.

Co z tego wynika:

- Przy 10 i 100 razy większym ruchu liczą się już tylko koszty zmienne. Serwer i domena to poniżej
  2% rachunku.
- Z kosztów zmiennych od 56 do 61% to tokeny modeli, reszta to kredyty wyszukiwarki. Przy 100 razy
  większym ruchu Tavily potrzebuje prawie 490 tys. kredytów miesięcznie, a największy plan z cennika
  ma 100 tys. Cena dla takiej skali: do negocjacji, UNCONFIRMED. Z cennika wychodzi, że plany
  z abonamentem wyjdą taniej niż opłata za zużycie dopiero przy dużym ruchu: Startup (220 USD za
  38 000 kredytów) plus 10 750 kredytów po 0,008 USD to 306 USD zamiast 382 USD przy 10 000
  sprawdzeń, a Growth plus 387 500 kredytów po 0,008 USD to 3600 USD zamiast 3892 USD przy 100 000.
  Przy 1000 sprawdzeń abonament się nie opłaca.
- Koszt modeli dzieli się na trzy etapy: wyodrębnianie
  ([prawdowid/verifier.py](../../prawdowid/verifier.py#L45)), ranking na Haiku 5.5
  ([prawdowid/rerank.py](../../prawdowid/rerank.py#L50)) i sędzia na Sonnet 5.5
  ([prawdowid/judge.py](../../prawdowid/judge.py#L64)). Pomiar 0,0182 USD za samo wyodrębnianie
  pochodzi z wersji na Opus 5.5, czyli z około jednej trzeciej kosztu modeli. Od #88 (`83d6c65`)
  wyodrębnianie domyślnie idzie na Sonnet 5.5, którego token kosztuje połowę tego co Opus. Przy
  tej samej liczbie tokenów byłoby to około 0,009 USD, czyli oszczędność około 0,009 USD na
  sprawdzeniu (około 18% kosztu modeli). Tego nie zmierzyliśmy, a jakość po zmianie modelu
  sprawdza #88, więc rachunek wyżej bierze górną granicę 0,0491 USD. Jak koszt dzieli się między
  ranking i sędziego, nie zmierzyliśmy. Dziennik sprawdzeń zapisuje każde wywołanie modelu z
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
([docs/eval-notes.md](../eval-notes.md)). Szybki przebieg na `edd34a5` (10 przypadków, wiersz w
HISTORY.md na `integration/r3`) dał 24,9 s. Próg z briefu to 30 s. Nie mierzyliśmy, ile sprawdzeń naraz
wytrzyma serwer, czasu p95, punktu nasycenia ani kosztu pod obciążeniem. Test obciążeniowy z
podmienionymi źródłami to #88.

Ustawienia w kodzie buildu `integration/r3` (`235209b`), który jest podstawą wdrożenia. To
konfiguracja, nie zmierzona przepustowość:

- Backend to jeden proces uvicorn ([Dockerfile](../../Dockerfile)). Limit 10 sprawdzeń na minutę z
  jednego adresu IP jest trzymany w pamięci tego procesu ([prawdowid/app.py](../../prawdowid/app.py#L43)).
  Wszyscy użytkownicy Discorda dzielą adres IP bota, więc i limit (#59).
- API kończy czekanie po 60 s, a całe sprawdzenie ma budżet 40 s
  ([prawdowid/pipeline.py](../../prawdowid/pipeline.py#L55)). Google Fact Check ma 15 s, EUvsDisinfo
  5 s w potoku, korpus 5 s, jedno zapytanie do wyszukiwarki 10 s, pobranie strony 8 s.
- Jedno sprawdzenie bada najwyżej 3 twierdzenia i wysyła po 3 zapytania na twierdzenie
  ([prawdowid/verifier.py](../../prawdowid/verifier.py)). Nie ma globalnej kolejki ani limitu wydatków.
- Serwer jest jeden i nie ma zapasowego ([docs/deploy.md](../deploy.md), sekcja „Known limits”).

Co widzi użytkownik, kiedy coś się kończy: jedenaste sprawdzenie w ciągu minuty dostaje HTTP 429 z
komunikatem po polsku. Brak klucza do modelu albo jego awaria daje komunikat techniczny. Gdy padną
wszystkie źródła twierdzenia, nie odpowie sędzia albo skończy się czas, twierdzenie dostaje „nie
sprawdzono” z powodem. Od #60 (w `integration/r3`) tak samo kończy się awaria źródła, które może
rozstrzygnąć werdykt (Fact Check albo wyszukiwarka), gdy dowodów nie starcza: wynik nie brzmi już
„brak wystarczających dowodów” ([prawdowid/pipeline.py](../../prawdowid/pipeline.py#L14)). Dotyczy
to też wyczerpania kredytów Tavily, bo dla kodu to zwykła awaria wyszukiwarki
([prawdowid/websearch.py](../../prawdowid/websearch.py#L190)). Korpus, jako plik na naszym dysku, nie
liczy się jako źródło, które odpowiedziało. Do czasu scalenia `integration/r3` ten sam przypadek na
`main` daje jeszcze „brak wystarczających dowodów” z dopiskiem o awarii. Alertu o kończących się
kredytach nie ma (#75).

Przy większym ruchu potrzebne będą kolejne procesy albo serwery i wspólny licznik limitu dla nich
wszystkich. Ile, wyjdzie z testu obciążeniowego:

```text
do uzupełnienia (#88):
liczba procesów = szczytowa liczba sprawdzeń na minutę / przepustowość jednego procesu
```
