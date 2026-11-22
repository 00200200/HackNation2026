<p align="center">
  <img src="docs/readme/banner.png" alt="faktczyfejk.pl: sprawdź, zanim podasz dalej" width="100%">
</p>

<p align="center">
  <b><a href="https://faktczyfejk.pl">faktczyfejk.pl</a></b> · HackNation 2026, challenge <b>Prawdowid</b><br>
  Michał Furgała · Łukasz Lenkiewicz · Dominik Galus
</p>

# faktczyfejk

Paste a message or a link you were sent. faktczyfejk splits it into claims and answers each one
in plain Polish, with the sources behind the answer: a quote, the publisher, the date and a link.
When the evidence is not there, it says so instead of guessing.

| One box for text or a link | The answer, claim by claim |
|---|---|
| <img src="docs/readme/home.png" alt="faktczyfejk.pl home page: the name, one box for text or a link" width="100%"> | <img src="docs/readme/answer.png" alt="An answer from the live API: two claims, each with its verdict, the answer's first words and what could not be established" width="100%"> |

The answer on the right is a real response from the live API (21.11.2026). Google Fact Check and
EUvsDisinfo were not configured on the server yet and web search found nothing, so both claims come
back as `brak wystarczających dowodów` ("nie udało mi się potwierdzić") with the reasons listed,
not as a guess.

## How an answer reads

<img src="docs/readme/verdicts.png" alt="Five verdicts and the first words of each answer: Tak, Nie, To wprowadza w błąd, Nie udało mi się potwierdzić, Tego nie da się sprawdzić" width="100%">

Answers follow the organiser's sample format: the first words come from the verdict, then the
sources by name. "Skopiuj odpowiedź na czat" copies the same text. A technical failure or a
request to clarify is a grey notice, never a verdict, and a claim whose sources all failed comes
back as `nie sprawdzono` with the reason.

## How it works

<img src="docs/readme/flow.png" alt="Pipeline: text or link, sources in parallel per claim, rerank, a model judge labels quotes, the verdict is set by rules in code" width="100%">

- **The model reads, the code decides.** Claude (through PydanticAI) splits the text into claims
  and labels quotes. The verdict comes from rules in `judge.decide()`.
- **Sources per claim, in parallel:** Google Fact Check Tools (fact-checkers' ratings), EUvsDisinfo as context only, the www.gov.pl site search, and
  Tavily web search restricted to allowlisted domains.
- **Privacy:** PESEL, phone, e-mail, account and card numbers are masked before the model. Checks
  are kept for 30 days and can be deleted per session.
- **Two channels, one API:** the web page and the Discord command `/sprawdz` call the same
  `POST /api/checks`.

Measured results live in [`evals/results/HISTORY.md`](evals/results/HISTORY.md), one row per eval
run with its commit and notes. Read [`docs/eval-notes.md`](docs/eval-notes.md) before quoting a number.

## Zgodność z wymaganiami

Wymagania pochodzą z opisu zadania Prawdowid (MSZ), sekcje 3 do 6. Tabele opisują kod z `main` (`1aa173f`) na 22.11.2026. "Zrobione" znaczy, że działa w kodzie i ma test albo pomiar. "Częściowo" znaczy, że działa z nazwanym brakiem. "Brak" znaczy, że tego nie ma. Przy zakazach "zrobione" znaczy, że kod ich przestrzega. Numery w nawiasach to zgłoszenia w repozytorium. Czego system nie obsługuje i jaki komunikat widzi wtedy użytkownik: [docs/unsupported.md](docs/unsupported.md).

### Minimalny zakres (sekcja 3)

| Wymaganie | Stan | Dowód i uwagi |
|---|---|---|
| Wejście: tekst przez responsywny interfejs WWW | częściowo | Strona w `frontend/` (nginx) wywołuje `POST /api/checks` z `prawdowid/app.py`. Długość wejścia jest walidowana, limit to 5000 znaków. Testy obejmują API (`tests/test_app.py`), a strony nie: testu frontendu ani sprawdzenia widoku na wąskim ekranie w repozytorium nie ma. |
| Wejście: adres URL | częściowo | `prawdowid/link.py` pobiera stronę (HTML i PDF, ochrona przed SSRF), a jej tekst idzie przez to samo `verify()`. Żaden z 73 przypadków eval nie ma adresu na wejściu, więc ta ścieżka nie jest zmierzona. Zgłoszenie [#63] opisuje obserwację na żywo z 21.11, której nie odtworzono w repozytorium: długa strona zużywa budżet 25 s i twierdzenia wracają jako `nie sprawdzono`. |
| Drugi kanał albo adapter demonstracyjny | częściowo | Komenda Discord `/sprawdz` (`prawdowid/discord_bot.py`) woła to samo `POST /api/checks` z nagłówkiem `X-Channel: discord` i ma testy (`tests/test_discord_bot.py`). Bot nie jest wdrożony, więc jury nie uruchomi go na naszym serwerze ([#59]). |
| Rozpoznanie jednego lub kilku twierdzeń | zrobione | Model dzieli tekst na twierdzenia i oznacza sprawdzalne (`prawdowid/verifier.py`). Werdykt dostaje do 5 z nich (`PRAWDOWID_MAX_CHECKED_CLAIMS`), reszta trafia na listę bez werdyktu. |
| Wyszukiwanie w opisanym zbiorze, co najmniej dwa typy źródeł, pokazanie użytych materiałów | częściowo | Na każde twierdzenie: Google Fact Check, wyszukiwarka www.gov.pl, Tavily na liście 15 domen (`prawdowid/websearch.py`) i EUvsDisinfo (samo trafienie nie wystarcza do werdyktu). Źródło ma tytuł, wydawcę, datę, link i cytat. Korpus (1158 rekordów) nie jest przeszukiwany przez `verify()` ([#74]), a według [#95] pobieranie gubi większość znalezionych stron (tego w repozytorium nie odtworzono). Strony z listą źródeł nie ma ([#83]). |
| Wynik, krótkie uzasadnienie, siła podstawy, ograniczenia | częściowo | `ClaimResult` (`prawdowid/contract.py`) ma werdykt, uzasadnienie, siłę, przesłanki, źródła i ograniczenia. Siła nie uwzględnia świeżości dowodów ([#67]), a pole "Uzasadnienie" pokazuje czasem powód sprawdzalności zamiast uzasadnienia werdyktu ([#68]). |
| Odpowiedź po polsku, prostym językiem | częściowo | Etykiety, komunikaty i odpowiedzi są po polsku, strona ma `lang="pl"`. Czytelności nie mierzyliśmy, a porównanie z przykładowymi odpowiedziami mentora jest otwarte ([#92]). |
| Zapis przebiegu: pytanie, czas, źródła, wynik | częściowo | `prawdowid/checklog.py` zapisuje zamaskowane pytanie, czas, kanał, status, czasy kroków, wywołania modeli, koszt oraz werdykt i źródła każdego twierdzenia. Na serwerze dziennik ginie przy każdym wdrożeniu, bo nie ma wolumenu ([#70]). |
| Wstrzymanie się bez dowodów | zrobione | `judge.decide()` (kod, nie model) zwraca `brak wystarczających dowodów`, gdy żadna strona nie ma zweryfikowanego cytatu z wystarczająco mocnego źródła (`prawdowid/judge.py`). Testy: `tests/test_judge.py`, na przykład `test_single_weak_source_is_insufficient`. W repozytorium nie ma ważnego pomiaru wstrzymania się na obecnym potoku (tabela metryk). |
| Pełna ścieżka bez ręcznej ingerencji | częściowo | W kodzie nie ma kroku ręcznego między zgłoszeniem a zapisem w dzienniku. Quick eval z commitu `95e6177` zaliczył 8 z 9 przypadków, ale na szkielecie sprzed sędziego (tabela metryk), więc nie dowodzi obecnego potoku. Dziewiąty, J01, wymaga symulowanej awarii, której eval nie potrafi wywołać. |

### Funkcje premiowane

| Funkcja | Stan | Dowód i uwagi |
|---|---|---|
| Obraz i dźwięk: OCR, transkrypcja, metadane, porównywanie obrazów | brak | Wejście to tekst i adres URL. Zrzut ekranu: [#80]. Nie deklarujemy wyszukiwania odwrotnego obrazu. |
| Porównywanie źródeł, łańcuch dowodowy | częściowo | Sędzia oznacza każdy fragment jako potwierdzający, obalający, kontekst albo lukę i podaje dokładny cytat (`prawdowid/judge.py`). Odpowiedź nie pokazuje tego stanowiska przy źródle ([#78]). |
| Wielojęzyczne wyszukiwanie, odpowiedź po polsku | brak | Zapytania są po polsku. Angielskie zapytania do EUvsDisinfo i źródeł międzynarodowych: [#89]. |
| Otwarty lub wymienny katalog źródeł z zasadami | częściowo | Katalog `corpus/catalog.yaml`, zasady włączania, aktualizacji i wykluczania oraz licencje w [docs/corpus.md](docs/corpus.md) i [docs/sources.md](docs/sources.md). Odświeżanie jest ręczne ([#90]), a publicznej strony ze źródłami nie ma ([#83]). |
| Podłączanie kanałów, modeli i źródeł bez przebudowy | częściowo | Kanały wołają to samo API, modele wybierają trzy zmienne środowiskowe (PydanticAI, ale `compose.yaml` przekazuje dziś do kontenera tylko `PRAWDOWID_MODEL`), a źródła zwracają wspólny `Source`. Podmiana na model spoza Claude nie była uruchomiona, a zainstalowany jest tylko dodatek `anthropic` (szczegóły w [docs/privacy.md](docs/privacy.md#where-data-is-processed)). |
| Dopasowanie do katalogu incydentów albo korpusu | częściowo | `prawdowid/incidents.py` dopasowuje wejście po adresie, domenie i podobieństwie tekstu i nigdy nie ustawia werdyktu. Baza incydentów organizatora nie jest wczytana, więc moduł jest pusty ([#64]), a korpus nie jest przeszukiwany ([#74]). |
| Eksport danych, integracje analityczne | częściowo | JSON z `POST /api/checks` i `GET /api/sessions/{id}`. CSV i STIX dla OpenCTI: brak ([#86]). Specyfikacja OpenAPI z FastAPI zwraca 404 na publicznym demo ([#87]). |
| Kontrolowana archiwizacja materiału wskazanego przez użytkownika | brak | Nic nie jest archiwizowane na prośbę użytkownika. Dziennik sprawdzeń trzyma skrót SHA-256 strony, nie jej treść. |
| Mniejsza zależność od dostawców spoza EOG, audyt, hosting własny, miejsce przetwarzania | częściowo | Serwer to OVHcloud VPS w Limburgu (DE), całość uruchamia Docker Compose z kodu z repozytorium. Dostawcy modeli i wyszukiwania działają poza naszą kontrolą: tabela dostawców i droga migracji w [docs/privacy.md](docs/privacy.md#where-data-is-processed). Przebiegu na modelu przetwarzanym w UE nie wykonano ([#85]). |
| Pętla informacji: sprawa moderatora, grupowanie podobnych zgłoszeń | brak | Nie zbudowana ([#79]). Eval pokazuje 0.0. |

### Wymagania formalne (sekcja 4)

| Wymaganie | Stan | Gdzie |
|---|---|---|
| Nazwa zespołu, tytuł, opis do 4000 znaków | częściowo | Szkic: [docs/submission/description.md](docs/submission/description.md), 2309 znaków. Nazwa zespołu to placeholder TEAM_NAME, a szkic nadal pisze, że nie zbudowaliśmy korpusu, który już jest ([#18]). |
| Prezentacja PDF, do 12 slajdów | brak | W repozytorium jest tylko konspekt: [docs/submission/slides-outline.md](docs/submission/slides-outline.md). Pliku PDF nie ma, jego stan poza repozytorium UNCONFIRMED ([#18]). |
| Film demonstracyjny, do 3 minut | brak | W repozytorium nie ma filmu ani linku do niego ([#18]). |
| Link do repozytorium z instrukcją uruchomienia | częściowo | Instrukcja: sekcja "Run" poniżej (uv i Docker Compose). Repozytorium jest prywatne (`gh repo view`, 22.11.2026), dostęp dla jury ustala zespół. |
| Opis architektury, przepływu danych, modeli, dostawców i ograniczeń | zrobione | [docs/submission/architecture.md](docs/submission/architecture.md), tablica architektury (link niżej) i [docs/privacy.md](docs/privacy.md). |
| Źródła, licencje, kwalifikacja i aktualizacja | częściowo | [docs/submission/sources.md](docs/submission/sources.md), [docs/sources.md](docs/sources.md) i [docs/corpus.md](docs/corpus.md). Prawa do części źródeł są oznaczone UNCONFIRMED, odświeżanie jest ręczne ([#90]). |
| Wyniki testów według sekcji 6 z danymi do odtworzenia | częściowo | 73 przypadki w `evals/cases.jsonl`, uruchomienie `uv run python -m evals.run`, wyniki w [evals/results/HISTORY.md](evals/results/HISTORY.md). Pełnego przebiegu na commicie zgłoszenia jeszcze nie ma ([#16]). |
| Ryzyka: halucynacje, stronniczość źródeł, prywatność, prompt injection, dostępność, nadużycia | zrobione | [docs/submission/risks.md](docs/submission/risks.md) ma wszystkie sześć, z istniejącymi zabezpieczeniami i miejscem w kodzie. |
| Opcjonalnie: publiczne demo, kontener Docker, OpenAPI, makiety kanałów, dashboard jakości | częściowo | Demo: https://faktczyfejk.pl. Docker: `compose.yaml`. OpenAPI: [#87]. Makiet kolejnych kanałów i dashboardu jakości nie ma. |

### Wymagania techniczne (sekcja 5)

| Obszar | Stan | Dowód i uwagi |
|---|---|---|
| Architektura: kanały oddzielone od logiki, wymiana modelu bez przebudowy | częściowo | Web i Discord wołają to samo API, a API jedno `verify()`. Modele wybierają `PRAWDOWID_MODEL`, `PRAWDOWID_RERANK_MODEL` i `PRAWDOWID_JUDGE_MODEL`, ale `compose.yaml` przekazuje do kontenera tylko pierwszą. Wymiana nie została wypróbowana ([docs/privacy.md](docs/privacy.md#where-data-is-processed)). |
| Fakty: dowód albo wstrzymanie, awaria, niejasne pytanie i wyjście poza zakres osobno | częściowo | Statusy `technical_error`, `cannot_check` i `needs_clarification` są szarą informacją, nie werdyktem, a opinie i prognozy dostają `nie podlega weryfikacji`. Wyjątki: awaria źródeł bywa pokazana jako `brak wystarczających dowodów` ([#60]), a `nie sprawdzono` wygląda jak werdykt ([#68]). |
| Źródła: co najmniej 100 dokumentów, 10 domen, dwa typy, źródła pierwotne i wtórne, lista do audytu | częściowo | `make corpus-check` na zapisanym korpusie: 1158 dokumentów, 11 domen rejestrowych (7, gdy wszystkie `*.gov.pl` liczyć jako jedną), typy `official` (1143) i `fact_checker` (15). Wiarygodnych źródeł wtórnych jest w korpusie tylko 15 rekordów Pravdy. Lista do audytu: `corpus/catalog.yaml`. Korpus nie jest przeszukiwany ([#74]). |
| Aktualność: znaczniki publikacji i pobrania, preferowanie świeżych, ostrzeżenie o archiwaliach | częściowo | `Source` ma `published_at` i `fetched_at`, a źródło starsze niż 730 dni dostaje ostrzeżenie o materiale archiwalnym (`PRAWDOWID_ARCHIVE_DAYS`, próg ustawiony na oko, nie dostrojony). W korpusie 259 z 1158 rekordów nie ma daty publikacji. Siła werdyktu nie zależy od świeżości ([#67]). |
| Bezpieczeństwo: walidacja wejścia, separacja instrukcji od treści źródeł, ograniczenia narzędzi, sekrety, limit żądań, logowanie zdarzeń | częściowo | Jest walidacja długości, dane źródeł w osobnych znacznikach, agenci bez narzędzi, limit 10 żądań na minutę na adres, sekrety w ignorowanych plikach `.env` ze skanem przed pushem i zdarzenia prompt injection w dzienniku. Odporność zmierzona w quick evalu to 0.000, ale na szkielecie sprzed sędziego (tabela metryk), a przypadków z wstrzyknięciem w pobranej stronie nie ma ([#61], [#94]). |
| Prywatność: minimalizacja, maskowanie, retencja, usunięcie sesji | częściowo | `prawdowid/privacy.py` maskuje e-mail, NRB i IBAN, kartę, PESEL i telefon przed modelem i w każdym logu. Retencja to 30 dni, a "Usuń moje sprawdzenia" na stronie woła `DELETE /api/sessions/{id}`. Maskowanie pomija numery dowodu i paszportu oraz część formatów telefonu ([#82]). Na Discordzie nie ma usuwania. |
| Obserwowalność: czas, użycie modeli, błędy wyszukiwania, wstrzymania, szacunkowy koszt | częściowo | Dziennik ma czas i czasy kroków, wywołania modeli z tokenami, `cost_usd` na odpowiedź, zdarzenia bezpieczeństwa oraz werdykt i ograniczenia każdego twierdzenia, więc błędy źródeł i wstrzymania da się z niego policzyć. Agregacji ani dashboardu nie ma, a dziennik ginie przy wdrożeniu ([#70]). |
| Dostępność: responsywny interfejs, kontrast, język bez wiedzy technicznej | częściowo | Strona ma `meta viewport`, `lang="pl"`, `aria-live` na wyniku i `prefers-reduced-motion`. W repozytorium nie ma pomiaru kontrastu ani testu z czytnikiem ekranu. |
| Kanały i dostęp: ta sama logika, spójny wynik | częściowo | Jedno API dla obu kanałów i test `test_same_input_same_result_on_web_and_discord` (`tests/test_discord_bot.py`), który uruchamia prawdziwą aplikację FastAPI w procesie, z atrapą modelu. Spójność na żywych źródłach nie jest zmierzona, bo drugi kanał nie jest wdrożony ([#59]). |
| Pętla informacji | brak | Nie zbudowana ([#79]). |
| Zależności zewnętrzne: klucze, limity, koszty, miejsce przetwarzania, zachowanie przy awarii | częściowo | Klucze i limity: sekcja "Configuration" poniżej. Koszty: [docs/submission/cost.md](docs/submission/cost.md). Miejsce przetwarzania: [docs/privacy.md](docs/privacy.md#where-data-is-processed), część UNCONFIRMED. Zachowanie przy awarii: [docs/unsupported.md](docs/unsupported.md). Demo może wyczerpać kredyty Tavily albo budżet modelu ([#75]). |
| Multimodalność (nieobowiązkowa) | brak | [#80]. |
| Koszt 1000 zapytań, koszt kanału, zachowanie przy ruchu | częściowo | [docs/submission/cost.md](docs/submission/cost.md): z quick evalu wynika USD 18.22 za 1000 sprawdzeń, ale to koszt samej ekstrakcji twierdzeń: ten przebieg (`95e6177`, 9 przypadków) nie miał jeszcze sędziego ani wyszukiwania. Koszt kanału i zachowanie pod obciążeniem: UNCONFIRMED. Ekstrakcja działa na Opusie, tańsze modele i test obciążenia: [#88]. |
| Bezpłatny dostęp dla użytkownika | częściowo | Aplikacja nie ma płatności ani logowania, więc użytkownik nie płaci. Kto pokrywa koszty operatora (hosting, klucze API) i ile wynoszą, nie jest wyliczone: UNCONFIRMED. |

### Zakazy

| Zakaz | Stan | Dowód i uwagi |
|---|---|---|
| Wynik modelu jako fakt bez źródła | zrobione | Werdykt ustawia kod w `judge.decide()` z cytatów, które kod sprawdził w tytule albo fragmencie źródła. Model tylko oznacza cytaty. |
| Obchodzenie zabezpieczeń serwisów i płatnych baz | zrobione | Pobieranie stron z wyników wyszukiwania i budowa korpusu respektują robots.txt (RFC 9309; wyjątek to udokumentowane wywołania API z kluczem), a korpus zatrzymuje się na 403, 429 i wyzwaniach antybotowych. Adres podany przez użytkownika jest pobierany na jego prośbę, z nagłówkiem User-Agent opisującym ten cel (`Prawdowid/0.1`), bez sprawdzania robots.txt, a paywall i ściana logowania kończą się prośbą o wklejenie tekstu. Wyszukiwarka www.gov.pl używa nieudokumentowanego endpointu samego serwisu, jego stabilność UNCONFIRMED. |
| Przesądzanie o prawdziwości z domeny, autora, kanału, popularności, udostępnień albo etykiety tego samego modelu | częściowo | Werdykt wymaga zweryfikowanego cytatu ze stanowiskiem, więc sama domena go nie daje. Domena ustala typ źródła (`ALLOWLIST` w `prawdowid/websearch.py`), a typ to, czy wystarczy jeden cytat ze źródła urzędowego, pierwotnego albo fact-checkera, czy potrzebne są dwa niezależne (`prawdowid/judge.py`). Autora, kanału i popularności nie ma w danych, z których `judge.decide()` liczy werdykt. EUvsDisinfo nie jest typem wiarygodnym, więc samo nie wystarcza, a baza incydentów nie wpływa na werdykt. Luka: tytuł recenzji z Fact Check, bez oceny fact-checkera, może sam przesądzić werdykt ([#66]). |
| Status źródła (np. sankcje UE) nie przesądza o prawdziwości, osobne neutralne ostrzeżenie | częściowo | Status źródła nie wpływa na werdykt, ale ostrzeżenia o statusie nie ma ([#81]). |
| Pełne wyszukiwanie odwrotne obrazu bez działającego API | zrobione | Nie deklarujemy go: wejście nie przyjmuje obrazów. |
| Archiwizacja pełnych treści i obrazów bez podstawy, licencji, retencji, kontroli dostępu i usunięcia | częściowo | Pełny tekst zapisujemy tylko tam, gdzie pozwala licencja albo warunki wydawcy, resztę jako fragment do 500 znaków, obrazów nie zapisujemy. Zasady, retencja i usuwanie na żądanie: [docs/corpus.md](docs/corpus.md). Wyjątek bez potwierdzonej podstawy: 251 rekordów Odyseusza ma pełny tekst (do 8000 znaków), a serwis nie podaje licencji. Podstawą jest art. 4 pkt 2 ustawy o prawie autorskim oraz to, że organizator wskazał Odyseusz jako źródło do pobrania (mentor, Discord, 21.11.2026). Czy to wystarcza na pełny tekst: UNCONFIRMED. |
| Brak klucza, limit albo awaria nie jako wynik merytoryczny | częściowo | Brak klucza modelu, limit żądań i przekroczenie czasu dają szarą informację, a nie werdykt. Wyjątek: gdy wszystkie źródła zawiodą, część odpowiedzi pokazuje `brak wystarczających dowodów` zamiast awarii ([#60]). |
| Klucze, dane osobowe i sekrety poza repozytorium i materiałami demo | zrobione | Pliki `.env*` są ignorowane, a hook `.githooks/pre-push` blokuje push z sekretami w zmienionych liniach i ze śledzonym plikiem `.env`. Korpus zawiera tylko materiał opublikowany przez wydawców, a `make corpus-check` odrzuca adres e-mail i numer z poprawną sumą PESEL ([docs/corpus.md](docs/corpus.md)). |

### Metryki obowiązkowe (sekcja 6)

Ostatnie pomiary pochodzą z [evals/results/latest.json](evals/results/latest.json): przebieg quick, 9 przypadków, commit produktu `95e6177`, 2026-11-21T19:10:57Z, drzewo czyste. Ten przebieg poprzedza sędziego, potok wyszukiwania i dziennik sprawdzeń. W commicie `95e6177` (kod `prawdowid/` jest identyczny w `e9a7f86` na `main`) weryfikator po ekstrakcji zwracał dla każdego sprawdzalnego twierdzenia stałe `brak wystarczających dowodów` (`prawdowid/verifier.py`, `to_check_result`), a `judge.py`, `pipeline.py` i `checklog.py` jeszcze nie istniały. Czas, koszt, wstrzymanie się, macro-F1, odporność i scenariusze end-to-end opisują więc ten szkielet, a nie obecny kod. Żadna z tych liczb nie jest pomiarem dzisiejszego produktu. Wszystkie wartości są do aktualizacji po pełnym evalu ([#16]). Każdy przebieg z commitem i uwagami jest w [evals/results/HISTORY.md](evals/results/HISTORY.md). Wiersz z pełnego przebiegu na 71 przypadkach (`8c6f396`) jest odtworzony z relacji osoby, która go uruchomiła, bez pliku JSON, i zniekształcony przez limity czasu modelu oraz budżet czasu sprawdzenia (25 s), więc nie służy jako pomiar ([docs/eval-notes.md](docs/eval-notes.md)).

| Metryka | Próg | Ostatni pomiar (do aktualizacji po pełnym evalu, #16) | Uwagi |
|---|---|---|---|
| Dokładność werdyktu, macro-F1 | ≥ 0.75 | 0.100, poniżej progu | Wszystkie 9 odpowiedzi to stałe `brak wystarczających dowodów` szkieletu. Analiza błędów: [#77]. |
| Pokrycie cytatami twierdzeń faktograficznych | ≥ 95% | brak pomiaru | W JSON wartość `null`. |
| Poprawność cytatów | ≥ 85% | brak pomiaru | Wymaga przebiegu z `--corpus`. Według [#62] część cytatów z żywych źródeł, które sędzia oznacza jako przeczące twierdzeniu, go nie obala (tego w repozytorium nie odtworzono). |
| Poprawne wstrzymanie się | ≥ 80% | 1.000, bez wartości dowodowej | Wynik trywialny: wszystkie odpowiedzi tego przebiegu to stałe wstrzymanie się, a nie decyzja sędziego. |
| Odporność na prompt injection | ≥ 90% | 0.000, poniżej progu | Przypadki mają wstrzyknięcie w tekście wejściowym, w pobranej stronie żadnego ([#61], [#94]). |
| Mediana czasu, tekst i adres URL | ≤ 30 s | 3.90 s, tylko ekstrakcja | Czas ekstrakcji twierdzeń, bez wyszukiwania i sędziego, na zestawie quick bez przypadków z adresem URL. W repozytorium nie ma ważnego pomiaru obecnego potoku. |
| Koszt 100 testów | do podania | USD 1.82, tylko ekstrakcja | Z `cost_usd`, przy ekstrakcji na Opusie ([#88]). Rerank i sędzia, dodane później, nie są w tej liczbie. |
| Scenariusze end-to-end bez zespołu | 100% | 0.889 (8 z 9), poniżej progu | Niezaliczony jest J01: eval nie stosuje pola `simulate`, więc awaria Fact Check nie jest wywołana i wraca `brak wystarczających dowodów` zamiast `technical_error`. FC-J01 i FC-J02 pominięte. Zaliczone przypadki sprawdzają kształt odpowiedzi szkieletu, nie obecny potok. |
| Spójność między kanałami | 100% | brak pomiaru | Drugi kanał nie jest podłączony do evalu ([#59]). |
| Pętla moderatora (jeśli wdrożona) | 100% | 0.0 | Nie zbudowana ([#79]). |

### Najważniejsze braki

- Pełny eval na commicie zgłoszenia nie był uruchomiony ([#16]). Ostatni pomiar (quick, szkielet sprzed sędziego) jest poniżej progu dla dokładności werdyktu, odporności na prompt injection i scenariuszy end-to-end, a pokrycie i poprawność cytatów są niezmierzone ([#77], [#62]). W repozytorium nie ma ważnego pomiaru obecnego potoku.
- Korpus nie jest przeszukiwany przez `verify()` ([#74]).
- Discord nie jest wdrożony ([#59]), więc spójność kanałów nie jest zmierzona.
- Brakuje pliku PDF z prezentacją, filmu i nazwy zespołu ([#18]).
- Nie zbudowano pętli moderatora ([#79]), wejścia z obrazu ([#80]) ani ostrzeżenia o statusie źródła ([#81]).
- Awaria źródeł bywa pokazana jako `brak wystarczających dowodów` ([#60]).
- Część dostawców przetwarza dane poza EOG albo w nieznanym miejscu. Tabela dostawców i droga migracji: [docs/privacy.md](docs/privacy.md#where-data-is-processed) ([#85]).

[#16]: https://github.com/00200200/HackNation2026/issues/16
[#18]: https://github.com/00200200/HackNation2026/issues/18
[#59]: https://github.com/00200200/HackNation2026/issues/59
[#60]: https://github.com/00200200/HackNation2026/issues/60
[#61]: https://github.com/00200200/HackNation2026/issues/61
[#62]: https://github.com/00200200/HackNation2026/issues/62
[#63]: https://github.com/00200200/HackNation2026/issues/63
[#64]: https://github.com/00200200/HackNation2026/issues/64
[#66]: https://github.com/00200200/HackNation2026/issues/66
[#67]: https://github.com/00200200/HackNation2026/issues/67
[#68]: https://github.com/00200200/HackNation2026/issues/68
[#70]: https://github.com/00200200/HackNation2026/issues/70
[#74]: https://github.com/00200200/HackNation2026/issues/74
[#75]: https://github.com/00200200/HackNation2026/issues/75
[#77]: https://github.com/00200200/HackNation2026/issues/77
[#78]: https://github.com/00200200/HackNation2026/issues/78
[#79]: https://github.com/00200200/HackNation2026/issues/79
[#80]: https://github.com/00200200/HackNation2026/issues/80
[#81]: https://github.com/00200200/HackNation2026/issues/81
[#82]: https://github.com/00200200/HackNation2026/issues/82
[#83]: https://github.com/00200200/HackNation2026/issues/83
[#85]: https://github.com/00200200/HackNation2026/issues/85
[#86]: https://github.com/00200200/HackNation2026/issues/86
[#87]: https://github.com/00200200/HackNation2026/issues/87
[#88]: https://github.com/00200200/HackNation2026/issues/88
[#89]: https://github.com/00200200/HackNation2026/issues/89
[#90]: https://github.com/00200200/HackNation2026/issues/90
[#92]: https://github.com/00200200/HackNation2026/issues/92
[#94]: https://github.com/00200200/HackNation2026/issues/94
[#95]: https://github.com/00200200/HackNation2026/issues/95

## Status in detail

The verifier sends the text to Claude (through PydanticAI) and gets back a list of
claims, each marked checkable or not. The model never decides whether a claim is true. Each
checkable claim then goes through `prawdowid/pipeline.py` in parallel with the others: Google Fact
Check, EUvsDisinfo known narratives (context only, never a verdict on its own), the www.gov.pl site
search (ministry and RCB pages; web search leaves www.gov.pl to it) and web search on
allowlisted domains (our own database, #19, is out of the pipeline for now), then
rerank and a judge that labels quotes; the verdict is set in code (`judge.decide`). The whole check
has one time budget (`PRAWDOWID_CHECK_BUDGET_S`, 25 s). A claim that runs out of time, or whose
web search, gov.pl, Fact Check and EUvsDisinfo all fail, comes back `not_checked` with the reason, never as a verdict. An
opinion, forecast or question is `not_verifiable`. A link is fetched (`prawdowid/link.py`) and the page's
main text is checked like pasted text; a blocked page, paywall, login wall, social media post,
private address or file that is not HTML or PDF comes back as `cannot_check` with a request to
paste the text. Personal data (PESEL, phone, e-mail, account and card numbers) is masked before
the text goes to the model. Each check is logged to stdout (session, status, latency, input length)
with a second line for the model call (model, input and output tokens, latency), and kept for 30
days as one masked record in the check log, which the user can delete per session. A link check
also logs the final URL with secret query values removed and personal data masked, the page's
SHA-256, and the text and verdict of every claim. The page text itself is never logged. Successful
web evidence fetches are cached in `corpus/docs.jsonl` as metadata only (full text only once a
domain's licence is confirmed, none today), one record per URL, dropped after 30 days. Details:
[docs/privacy.md](docs/privacy.md), [submission risks](docs/submission/risks.md).

## Configuration

Put these in `.env` in the repository root. The file is git-ignored and is not copied into the
image. `make dev` loads it into the API environment. Compose reads it for interpolation but only
forwards variables declared in `compose.yaml`: the backend gets `ANTHROPIC_API_KEY`,
`PRAWDOWID_MODEL`, `GOOGLE_FACTCHECK_API_KEY`, `TAVILY_API_KEY`, `EUVSDISINFO_API_KEY` and
`PRAWDOWID_INCIDENTS_PATH`, and its check log and source cache already point at a writable `/tmp`
path. Other tuning variables need an explicit Compose environment override.

| Variable | Required | Default | What it does |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | yes | none | Anthropic API key. Without it every check returns `technical_error`. |
| `PRAWDOWID_MODEL` | no | `anthropic:claude-opus-5-5` | PydanticAI model id (`provider:model`). |
| `PRAWDOWID_CHECK_BUDGET_S` | no | `25` | Time budget for the whole check, in seconds. Claims still running at the end are `not_checked`. |
| `PRAWDOWID_WEB_SEARCH_BUDGET_S` | no | `10` | Longest one web search query may take, retry included, before it counts as unavailable. |
| `PRAWDOWID_PAGE_BUDGET_S` | no | `8` | Longest one page fetch may take (robots.txt and page); a slower page is skipped, the others are kept. |
| `PRAWDOWID_GOVPL` | no | `1` | `0` switches off the www.gov.pl site search (`prawdowid/govpl.py`); its queries then go to web search, which searches www.gov.pl again. See [docs/sources.md](docs/sources.md). |
| `PRAWDOWID_RETRY_MIN_S` | no | `18` | A claim without enough evidence is searched once more only if at least this many seconds remain. |
| `DISCORD_BOT_TOKEN` | only for the Discord bot | none | Bot token from the Discord developer portal. Without it the bot refuses to start. |
| `PRAWDOWID_API_URL` | no | `http://127.0.0.1:8000` | API the Discord bot calls (`http://backend:8000` in Docker). |
| `GOOGLE_FACTCHECK_API_KEY` | no | none | Google API key with the Fact Check Tools API enabled. Without it the known-claim lookup is skipped and reported as unavailable. |
| `TAVILY_API_KEY` | no | none | Tavily API key (`tavily-python`) for web search on allowlisted domains (step 2b). Without it the web search is skipped and reported as unavailable. |
| `DOMAIN` | with `compose.prod.yaml` | none | Public domain Caddy gets the HTTPS certificate for (`compose.prod.yaml`, see `docs/deploy.md`). |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | with `compose.prod.yaml` | none | Database, user and password of the `db` service. `compose.prod.yaml` passes them to the backend as `DATABASE_URL`. `POSTGRES_PASSWORD` is also the password of the local `sourcedb` service (default `prawdowid`, port bound to 127.0.0.1 only), applied only when its `sourcedb_data` volume is created; see [deletion instructions](docs/sources.md). `make db-seed` refuses until the team approves sources for full-text storage; see [the prerequisite](docs/sources.md#full-text-seed-approval). |
| `DATABASE_URL` | no | none | Postgres URI of the step 2c source store, used only by the seed script (`make db-seed` sets it) and `cache.search_documents`. Step 2c is disabled in the pipeline until licensed sources are chosen, so checks never read or write the database. The backend never needs it; `compose.prod.yaml` sets it for production's separate `db`, which has no source-store schema, so enabling step 2c in production needs this migration applied there first. Start the database with `make db` (127.0.0.1:5433). The corpus search (`prawdowid/corpus_search.py`) reads its own tables (`corpus_documents`, `corpus_chunks`) from the same database; `make index` builds them from `corpus/evidence.jsonl`. |
| `EUVSDISINFO_API_KEY` | no | none | Personal API key for the EUvsDisinfo MCP server (`https://mcp.euvsd.info/mcp`), generated on euvsdisinfo.eu. Sent as the `X-API-Key` header. Without it the EUvsDisinfo lookup is skipped and reported as unavailable. |
| `PRAWDOWID_CHECK_LOG` | no | `logs/checks.jsonl` | Check log file (masked question, result, session id). Docker sets `/tmp/prawdowid/checks.jsonl`. See [docs/privacy.md](docs/privacy.md). |
| `PRAWDOWID_INCIDENTS_PATH` | no | `prawdowid/data/incidents.json` (empty) | Scenario I incident base, a `.json` or `.csv` file; format in `prawdowid/incidents.py`. Put the file in `incidents/` (git-ignored) and set a path relative to the repository root, e.g. `incidents/base.csv`: `make dev` reads it from the repository, Docker from `/app/incidents/base.csv`, where `compose.yaml` mounts `incidents/` read-only. The file must be readable by every user (the container runs as `nobody`). Read on the first check and kept: restart the backend after changing it. A match is shown next to the claims and never changes a verdict. |
| `PRAWDOWID_EMBEDDING_MODEL` | no | `intfloat/multilingual-e5-large` | Local embedding model for corpus search (fastembed). Changing it rebuilds the index on the next `make index`. |
| `FASTEMBED_CACHE_PATH` | no | fastembed's temp dir | Where the embedding model files are kept (`/models` in the image). |

The extraction call has a 45 s provider request timeout and at most one SDK retry, but shares
the 25 s whole-check deadline with URL fetching and per-claim checks, inside the API's 60 s
limit. Extraction errors and a missing model key return `technical_error`; a
model refusal returns `cannot_check`. Both carry a Polish message and no claims. Retrieval
failures are reported per claim. A judge-model outage becomes `not_checked` with a limitation;
a failed retry judgement can retain the first-pass assessment with a warning when first-pass
candidates existed.

## Run

Needs Docker with Compose and an Anthropic key in ignored `.env` for live model calls.
The model IDs listed above and in [architecture](docs/submission/architecture.md) are literal code
defaults; availability of those IDs on your account is UNCONFIRMED. Without working model
credentials, the UI opens but verification returns a technical notice.

```bash
make up
```

Open http://localhost:8080. Stop with `make down`. Use another port with `make up PORT=9000`.

Without `make`: `docker compose up --build -d`.

The base stack forwards `GOOGLE_FACTCHECK_API_KEY`, `TAVILY_API_KEY` and `EUVSDISINFO_API_KEY`,
and already points the check log and source cache at a writable `/tmp` path.

Add `--profile discord` before `up`
to start the bot too. Set `DISCORD_BOT_TOKEN` in `.env`, install the application in your Discord
server with slash-command access, then use `/sprawdz tekst:`. Live Discord transport has not
been verified in the saved eval; a token alone does not prove the bot is installed.

For the local API, install [uv](https://docs.astral.sh/uv/getting-started/installation/), run
`make install`, then `make dev`; `.env` is loaded by that target. Open the API docs at
http://127.0.0.1:8000/docs. In another terminal, `make discord` loads the same `.env` and calls
the local API. This path does not serve the web frontend. PostgreSQL is optional and disabled
in checks; do not seed it until source permissions are confirmed.

Public deployment with HTTPS on a server: [docs/deploy.md](docs/deploy.md).

Run `make help` to list every target. The ones used most:

| Target | What it does |
|---|---|
| `make up` / `make down` / `make logs` | Docker stack: frontend on `PORT` (default 8080), backend internal only |
| `make dev` | API alone on http://127.0.0.1:8000 with reload (docs at `/docs`) |
| `make discord` | Discord bot against `make dev`; `make up DISCORD=1` runs it in Docker |
| `make check` | `ruff format --check`, `ruff check`, `pytest` |
| `make format` | Format and autofix |
| `make corpus` / `make corpus-check` | Rebuild the evidence corpus from its source catalogue / check it against the brief's thresholds |
| `make index` | Load `corpus/evidence.jsonl` into Postgres for search (needs `DATABASE_URL`) |

## Architecture board

The team's architecture whiteboard: https://claude.ai/artifact/W9KUaX37YHjRFjAzZedyvs

## Layout

- `frontend/`: static `index.html`, `styles.css` and `app.js` (no build step) served by nginx.
  nginx also proxies `/api/` and `/health` to the backend, caps request bodies at 64 KB and sets
  a strict Content-Security-Policy.
- `Dockerfile`: the backend image (Python 3.13, uv, runs as `nobody`).
- `compose.yaml`: both services. Only the frontend port is published.
- `compose.prod.yaml`, `caddy/Caddyfile`: production overlay. Caddy serves HTTPS in front of nginx
  and is then the only service with published ports; `db` is Postgres 18 with pgvector and pg_trgm.
- `deploy/`: the server's deploy script and systemd timer. The demo server picks up a push to the
  `prod` branch within about a minute and then builds and starts it; setup in `docs/deploy.md`.
- `prawdowid/contract.py`: `Verdict`, `Status`, `Source`, `ClaimResult`, `CheckResult` (with `page`,
  `security_events`, `cost_usd`).
- `prawdowid/privacy.py`: `mask_personal_data` and `RETENTION_DAYS`; `prawdowid/checklog.py`: the check log
  per demo session (`DELETE /api/sessions/{id}` removes a session).
- `prawdowid/link.py`: `fetch_page(url)`, the guarded fetch and text extraction for link input.
- `prawdowid/verifier.py`: `async def verify(text) -> CheckResult`, the one function every
  channel calls. Holds the PydanticAI agent, its prompt and `to_check_result`, the pure function
  that turns the model's claims into verdicts.
- `prawdowid/factcheck.py`: `search_claims(claim)`, the known-claim lookup in Google Fact Check
  Tools (`claims:search`). Each review becomes a `Source` (`source_type="fact_check"`) with the
  fact-checker's rating and the reviewed claim kept beside it, not in `fragment`: the rating is a
  signal, not a verdict. One retry on a network error or 5xx, 15 s deadline for the whole lookup. A missing key, 4xx (bad key, quota) or outage returns a `limitation`
  message and no hits. Called per claim from `prawdowid/pipeline.py` (#11).
- `prawdowid/corpus_search.py`: `search_corpus(query)`, hybrid search in the evidence corpus
  (pgvector nearest chunks and Postgres full-text, merged by reciprocal rank fusion, at most two
  chunks per document). Each hit is a `Source` whose `fragment` is a verbatim chunk of the stored
  document, plus the fact-checker's rating and reviewed claim for fact-checks. 10 s deadline; no
  database or an error returns a `limitation`. Not wired into `verify()` yet.
  `prawdowid/index.py` builds the tables (`make index`), `prawdowid/embeddings.py` holds the
  local embedding model.
- `prawdowid/app.py`: the API, input validation, rate limit, and the `technical_error` path.
- `prawdowid/discord_bot.py`: the second channel, a `/sprawdz tekst:` slash command (discord.py).
  It sends the same `POST /api/checks` as the web form, with `X-Channel: discord`, and renders the
  `CheckResult` with the same sections (verdict, reasoning, strength, premises, sources with
  quotes, limitations). User and source text is escaped and messages never ping anyone. An answer
  goes out in at most 5 messages of 2000 characters; whatever does not fit is in an attached
  `odpowiedz.md` with the whole answer. API errors are shown as notices.
  The bot shares one API rate limit (10 per minute) for all its users.
- `corpus/`: the evidence corpus. `catalog.yaml` is the audited source list with its rules,
  `evidence.jsonl` the collected records, `manifest.json` the last build, `build.py` and `sources/`
  the collectors. Sources, licences and limits: [`docs/corpus.md`](docs/corpus.md).

## API

| Method and path | What it does |
|---|---|
| `POST /api/checks` | Body `{"input": "..."}`. Returns `CheckResult`. 60 s timeout on `verify`; 10 requests per minute per client IP. |
| `GET /health` | Liveness. |

Input is trimmed and must be 1 to 5000 characters. A single token containing `://` counts as a
link and must be a valid `http` or `https` URL. The page is fetched only from public addresses
(checked on every connection, so redirects and DNS cannot reach private, loopback or link-local
hosts), with at most 3 redirects (their bodies are never read), a 10 s deadline and a 2 MB cap.
The URL policy (scheme, social media hosts, login pages) is applied before every hop. HTML goes
through trafilatura and PDF through pypdf in a child process (`prawdowid/extract_worker.py`) that
is killed at the deadline; at most 2 run at once per API process. The parsers stop after 50 PDF
pages, 20,000 characters and 20 MB decompressed per stream; on Linux the child is also capped at
1 GB of memory and 15 s of CPU. Title, publisher, date and text together are cut to 5000
characters for the verifier. `CheckResult.page` carries the
page URL, content hash, title, publisher and date, never the page text. Validation errors come
back as 422 with a Polish message in `detail[0].msg`.

`ClaimResult` carries `verdict_label`, the Polish label for its verdict, so channels do not keep
their own copy of the labels.

## Submission drafts

Submission drafts: [description](docs/submission/description.md),
[architecture and exact test results](docs/submission/architecture.md),
[sources](docs/submission/sources.md), [risks](docs/submission/risks.md),
[cost](docs/submission/cost.md), [Polish slide outline](docs/submission/slides-outline.md),
[unsupported cases and their messages](docs/unsupported.md) (Polish).
The PDF and demo video remain open human work under [#18](https://github.com/00200200/HackNation2026/issues/18).

## Pre-push gate

Run once per clone:

```bash
git config core.hooksPath .githooks
```

`.githooks/pre-push` refuses a push without a `judge` agent PASS for the pushed commit, and on secrets, tracked
`.env` files, files over 10 MB, or failing ruff or pytest. Once an eval has run in the clone, product changes also
need a clean eval run on the pushed commit (`uv run python -m evals.run --quick`). Eval runs print one line per
finished case and take `--concurrency N`, `--resume`, `--retry-failed`, `--only` and `--note` (see the prawdowid-eval
skill). The submission push is
`HN_FINAL=1 git push`. Rules: `.claude/skills/hacknation-judging/SKILL.md` and `.claude/skills/prawdowid-eval/SKILL.md`.

Every eval run is logged in [`evals/results/HISTORY.md`](evals/results/HISTORY.md) (one row per run, full JSON
under `evals/results/history/`), not only `evals/results/latest.json`. Read
[`docs/eval-notes.md`](docs/eval-notes.md) first: it explains why some past runs are distorted. **Rule: check the
commit and the notes column before concluding anything from a number.**
