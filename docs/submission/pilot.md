# Pilotaż z MSZ: pięć etapów i co już mamy

Stan na 22.11.2026, gałąź `main` (commit `1aa173f`). Brief zadania w rozdziale 9 zaleca po
hackathonie pięć etapów. Przy każdym piszemy, co już jest w repozytorium, czego brakuje i ile pracy
to według nas zajmie. Pracochłonność podajemy w osobodniach jednej osoby z zespołu. To szacunek, nie
pomiar, i zespół potwierdza go przed rozmową z MSZ. Numery z krzyżykiem (#74) to zgłoszenia w
[repozytorium](https://github.com/00200200/HackNation2026/issues). Stan kodu opisujemy dla
buildu `integration/r3`, na którym oprzemy wdrożenie. Gdy coś jest tylko tam, a nie na `main`,
piszemy to przy danym zdaniu. #100 (krótkie klucze Fact Check i mapa ocen) i #116 (adapter
demo `/czat`) są w `integration/r3` (PR #126), więc wchodzą w ten opis, tak jak reszta tego buildu.

## Tryb pracy: wsparcie decyzji, publikację zatwierdza człowiek

Brief chce, żeby pilotaż ruszył od wąskiego, dobrze opisanego obszaru o niskim ryzyku. Odpowiedź,
która ma zostać opublikowana, zatwierdza człowiek. Szerszy dostęp przychodzi dopiero po osiągnięciu
uzgodnionych progów jakości.

Część tego działa już dziś:

- Model nie rozstrzyga, co jest prawdą. Wyodrębnia twierdzenia i oznacza cytaty, a werdykt wylicza
  funkcja `judge.decide()` z dowodów, których cytat znaleźliśmy dosłownie w źródle
  ([prawdowid/judge.py](../../prawdowid/judge.py), [ADR 0001](../adr/0001-evidence-retrieval-and-verdict.md)).
- Gdy odpowiedź ma dowody, pokazuje przy nich tytuł źródła, wydawcę, link i cytat oraz daty
  publikacji i pobrania, o ile je znamy: strona bez daty publikacji jest dopuszczona (#95, tylko w `integration/r3`; `main` takie strony odrzuca), a
  odpowiedź bez dowodów nie ma żadnego źródła do pokazania. Pokazuje też, czego nie udało się
  ustalić ([frontend/public/app.js](../../frontend/public/app.js)).
- Bez dowodów odpowiedź brzmi „Nie udało mi się potwierdzić tej informacji”. Gdy padną wszystkie
  źródła twierdzenia albo skończy się czas, twierdzenie dostaje „nie sprawdzono” z powodem, a
  awaria modelu daje komunikat techniczny ([prawdowid/pipeline.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/pipeline.py#L177-L193)).
  Dotyczy to także awarii samego źródła, które może rozstrzygnąć werdykt (Fact Check albo
  wyszukiwarka), gdy dowodów nie starcza (#60). Ta reguła jest w `integration/r3` (PR #109), a na
  `main` jeszcze jej nie ma: tam taki wynik brzmi „brak wystarczających dowodów” z dopiskiem, które
  źródło nie odpowiedziało.
- Każde sprawdzenie zostawia jeden zamaskowany wpis w dzienniku: pytanie, czas, źródła, werdykty,
  czasy kroków, wywołania modelu i koszt ([prawdowid/checklog.py](../../prawdowid/checklog.py),
  [docs/privacy.md](../privacy.md)). Ekspert ma z czego odtworzyć, skąd wzięła się odpowiedź.

Brakuje samego kroku zatwierdzania. Proponujemy kolejkę eksperta, czyli rozszerzenie #79. Odpowiedź
przeznaczona do publikacji trafia do kolejki razem ze źródłami i wpisem z dziennika. Ekspert ją
zatwierdza, poprawia albo odrzuca, a publikujemy tylko zatwierdzone. Decyzja zostaje w dzienniku z
osobą i godziną. Powtarzające się pytania bez odpowiedzi („brak wystarczających dowodów”) zakładają
jedną sprawę dla eksperta zamiast wielu. Szacunek: 4-6 osobodni (sprawy z #79 to 2-3, zatwierdzanie
ze śladem decyzji kolejne 2-3).

Na start proponujemy bezpieczeństwo podróży. To propozycja zespołu do uzgodnienia z MSZ. Źródło jest
po stronie ministerstwa: korpus ma już 239 profili krajów z serwisu Odyseusz, każdy z aktualnym
komunikatem i poziomem ostrzeżenia ([docs/corpus.md](../corpus.md)). Na pytanie „Czy MSZ odradza
podróże do...?” istnieje jedna urzędowa odpowiedź, więc łatwo sprawdzić, czy narzędzie ją podaje.
W buildzie `integration/r3` każde sprawdzenie przeszukuje korpus (#74, BM25 po `corpus/evidence.jsonl`,
w tym 251 dokumentów z Odyseusza). Na `main` korpusu jeszcze nie czyta. Nie mierzyliśmy, czy pytanie
o podróż faktycznie trafia na właściwy profil kraju i czy cytat z niego przechodzi sędziego:
`citation_correctness` jest niezmierzone, a tego pytania nie ma w zestawie testowym. To pierwsza
praca etapu 2.

## Etap 1. Odtworzenie wyników, przegląd licencji, bezpieczeństwa i architektury

Co już jest:

- Uruchomienie jednym poleceniem: `make up` (Docker Compose) albo `make dev`, opis w
  [README](../../README.md#run). Wersje zależności są zamrożone w [uv.lock](../../uv.lock).
  Wdrożenie krok po kroku: [docs/deploy.md](../deploy.md). Serwer co minutę pobiera gałąź `prod`
  ([deploy/pull-deploy.sh](../../deploy/pull-deploy.sh)), a do `prod` trafia tylko kod z `main`.
- Testy: `make check` uruchamia ruff i pytest. 22.11.2026 na `1aa173f` przechodzi 547 testów, 8 jest
  pominiętych.
- Pomiary do powtórzenia: [evals/run.py](../../evals/run.py) liczy metryki z briefu na 73 przypadkach na `main` (86 w `integration/r3`, z czego pełny przebieg na `ca48b84` ocenił 75)
  ([evals/cases.jsonl](../../evals/cases.jsonl)). Każdy przebieg ląduje w
  [evals/results/HISTORY.md](../../evals/results/HISTORY.md) z commitem i uwagami, a
  [docs/eval-notes.md](../eval-notes.md) mówi, którym przebiegom nie ufać.
- Architektura: [architecture.md](architecture.md) i [ADR 0001](../adr/0001-evidence-retrieval-and-verdict.md).
- Licencje: każde źródło korpusu ma podstawę prawną i zakres tego, co przechowujemy
  ([docs/corpus.md](../corpus.md), [corpus/catalog.yaml](../../corpus/catalog.yaml)). Warunki
  dostawców wyszukiwania opisują [sources.md](sources.md) i [docs/sources.md](../sources.md). Font
  Figtree jest na licencji SIL OFL ([frontend/public/fonts/OFL.txt](../../frontend/public/fonts/OFL.txt)).
- Bezpieczeństwo: rejestr ryzyk z odwołaniami do kodu ([risks.md](risks.md)). Pobieranie stron
  sprawdza adres IP przy każdym połączeniu i respektuje robots.txt
  ([prawdowid/safefetch.py](../../prawdowid/safefetch.py)). Jeden adres IP może wysłać 10 sprawdzeń
  na minutę ([prawdowid/app.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/app.py#L43)). Hook przed `git push` blokuje sekrety,
  śledzone pliki `.env`, pliki powyżej 10 MB, czerwone ruff albo pytest i commit bez akceptacji
  agenta-sędziego. Od pierwszego evalu w danym klonie przepuszcza zmianę kodu produktu tylko z evalem
  na tym samym stanie kodu ([.githooks/pre-push](../../.githooks/pre-push)).

Czego brakuje:

- Repozytorium nie ma własnej licencji (brak pliku `LICENSE`). Bez niej MSZ nie ma jasnej podstawy,
  żeby użyć kodu. To decyzja zespołu.
- Zestawienia licencji zależności (SBOM) wygenerowanego z `uv.lock`.
- CI. GitHub Actions są zablokowane na koncie (decyzja z 21.11 w [WORKLOG](../../WORKLOG.md)), więc
  kontrole robi hook na komputerze osoby, która wypycha kod. Hook sam uruchamia ruff i pytest, ale
  evalu nie puszcza: czyta tylko wynik ostatniego przebiegu w danym klonie. Słaby wynik blokuje
  dopiero zgłoszenie końcowe (`HN_FINAL=1`), przy zwykłym pushu hook tylko ostrzega. Hook włącza
  się raz na klon i ma awaryjne obejścia (`HN_SKIP_EVAL=1`, `HN_SKIP_JUDGE=1`). WORKLOG odnotowuje
  scalenia wypchnięte z `HN_SKIP_EVAL=1`. W pilotażu kontrole powinny chodzić na infrastrukturze,
  którą kontroluje MSZ, i nie dawać się obejść.
- Potwierdzenia, gdzie dostawcy przetwarzają dane. Dziś to UNCONFIRMED (#85).
- Niezależnego przeglądu bezpieczeństwa, na przykład testu penetracyjnego zleconego przez MSZ.
- Do powtórzenia pomiarów potrzebne są klucze do Anthropic, Tavily, Google Fact Check i EUvsDisinfo.
  README opisuje, co się dzieje bez nich, ale kluczy nie da się dołączyć do repozytorium.

Szacunek: 2-3 osobodni po stronie zespołu (licencja, SBOM, CI, tabela przetwarzania z #85). Przegląd
bezpieczeństwa zależy od kalendarza MSZ.

## Etap 2. Od 4 do 6 tygodni na zamkniętym korpusie, z kolejką ekspercką

Co już jest:

- Zamknięty korpus [corpus/evidence.jsonl](../../corpus/evidence.jsonl): 1158 dokumentów z 11
  zarejestrowanych domen, 1143 urzędowe i 15 od fact-checkera. Każdy rekord ma datę pobrania i
  licencję. Datę publikacji ma 899 z 1158; reszta stron jej nie podaje, w większości komunikaty
  CERT (241). Buduje go `make corpus` z listy [corpus/catalog.yaml](../../corpus/catalog.yaml),
  a `make corpus-check` sprawdza progi z briefu ([docs/corpus.md](../corpus.md)).
- Wyszukiwanie w korpusie podczas sprawdzenia to BM25 w pamięci po `corpus/evidence.jsonl`, bez
  embeddingów ([prawdowid/corpus_bm25.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/corpus_bm25.py), tylko w `integration/r3`). Osobny
  indeks pgvector z wyszukiwaniem pełnotekstowym i embeddingami e5-large, liczonymi lokalnie
  ([prawdowid/corpus_search.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/corpus_search.py), [prawdowid/index.py](https://github.com/00200200/HackNation2026/blob/235209b/prawdowid/index.py)),
  jest przygotowany, ale sprawdzanie go nie używa. Tekst nie wychodzi z serwera i nie płacimy za zapytanie.
- Dziennik sprawdzeń, który ekspert może przejrzeć ([prawdowid/checklog.py](../../prawdowid/checklog.py)),
  oraz odczyt sesji przez `GET /api/sessions/{id}`.
- Ten sam zestaw pomiarów można puszczać co tydzień ([evals/run.py](../../evals/run.py)).

Czego brakuje:

- Pomiaru, że korpus poprawia odpowiedzi. Wyszukiwanie w nim jest podpięte do `verify()` w
  `integration/r3` (#74), ale nie ma jeszcze pełnego przebiegu na tym stanie (#16). Odpowiedzi
  biorą dowody z Google Fact Check, EUvsDisinfo, wyszukiwarki www.gov.pl, Tavily i korpusu.
- Trybu „tylko zamknięty korpus”, który na czas pilotażu wyłącza otwartą wyszukiwarkę. Dziś osobnym
  przełącznikiem da się wyłączyć tylko wyszukiwarkę gov.pl (`PRAWDOWID_GOVPL=0`).
- Kolejki eksperta i zatwierdzania publikacji (opis wyżej, #79).
- Harmonogramu odświeżania szybkich źródeł urzędowych na serwerze (#90).
- Drogi, która zamienia poprawki eksperta w nowe przypadki testowe.

Szacunek: 8-11 osobodni (pomiar korpusu po #74: 1-2, tryb zamkniętego korpusu: 1, kolejka z zatwierdzaniem: 4-6,
#90: 1, poprawki jako przypadki testowe: 1). Do tego sam pilotaż, od 4 do 6 tygodni z ekspertami MSZ.

## Etap 3. Red team, ochrona danych, dostępność i konsultacje z użytkownikami

Co już jest:

- Scenariusz E w ewaluacji: 7 przypadków z poleceniem wstrzykniętym w treść i słowem-kanarkiem,
  które nie może trafić do odpowiedzi ([evals/cases.jsonl](../../evals/cases.jsonl)). Zdarzenia
  bezpieczeństwa zapisujemy bez treści ataku ([prawdowid/contract.py](../../prawdowid/contract.py)),
  a strona i Discord mówią użytkownikowi, że polecenia pominęliśmy.
- Ochrona danych: e-maile, numery kont (IBAN/NRB), karty, PESEL i telefony maskujemy, zanim tekst
  trafi do modelu, i w każdym logu ([prawdowid/privacy.py](../../prawdowid/privacy.py)). Zapis
  sprawdzenia trzymamy 30 dni. Użytkownik usuwa swoje sprawdzenia przyciskiem „Usuń moje
  sprawdzenia”. Tekstu stron z linków nie zapisujemy ([docs/privacy.md](../privacy.md)).
- Dostępność: agent `a11y-reviewer` przegląda pod kątem WCAG 2.2 AA każdą zmianę strony
  ([.claude/agents/a11y-reviewer.md](../../.claude/agents/a11y-reviewer.md)). Poprawki z przeglądów
  są w [WORKLOG](../../WORKLOG.md): fokus zostaje na miejscu podczas sprawdzania, błędy mają
  `aria-invalid`, obramowania pól mają kontrast 3,9:1.

Czego brakuje:

- Zewnętrznego red teamu. Mamy tylko własne przypadki, a wzorce wykrywania pisaliśmy, znając
  pierwsze trzy przypadki E ([WORKLOG](../../WORKLOG.md), wpis do #15). Potrzebne są przypadki,
  których nie widzieliśmy. Przypadki z poleceniem ukrytym w stronie źródłowej mają fixtures w
  `integration/r3` (#94), ale eval z nimi jeszcze nie był uruchomiony: pełny przebieg na `ca48b84` pominął E05-E15 (11 przypadków), bo brakowało publicznego adresu strony z fixture (`PRAWDOWID_FIXTURE_BASE`). Sprawdzanie pobranych źródeł wzorcami (#61, PR #72) jest w
  `integration/r3`, nie w `main`.
- Oceny skutków dla ochrony danych (DPIA) z inspektorem ochrony danych MSZ i umów powierzenia z
  dostawcami. Maskowanie nie łapie numerów dowodów, paszportów i części formatów telefonu (#82).
  Discord nie ma polecenia usuwania, a logi `stdout` Dockera są poza 30-dniową retencją
  ([docs/privacy.md](../privacy.md)).
- Audytu WCAG przez zewnętrznego audytora i testów z osobami, które korzystają z czytnika ekranu.
- Konsultacji z użytkownikami. W repozytorium nie ma żadnego badania z użytkownikami.

Szacunek: 6-8 osobodni po stronie zespołu (nowe przypadki red team i poprawki: 3-5, #82: 1, usuwanie
w Discordzie: 1, poprawki po audycie WCAG: 1). DPIA, audyt i konsultacje to kalendarz MSZ, w naszej
ocenie od 2 do 4 tygodni.

## Etap 4. Ograniczone wdrożenie publiczne

Brief wymienia tu monitoring jakości, procedurę korekt i kanał zgłoszeń.

Co już jest:

- Publiczna wersja na https://faktczyfejk.pl, na jednym serwerze w UE (OVHcloud, Limburg, Niemcy),
  z HTTPS przez Caddy. Na produkcję trafia tylko kod, który już jest na `main` ([docs/deploy.md](../deploy.md)).
- Endpoint `/health`, limit zapytań i dziennik, w którym każde sprawdzenie ma czasy kroków, błędy i
  koszt odpowiedzi ([prawdowid/checklog.py](../../prawdowid/checklog.py)).
- Historia pomiarów jakości ([evals/results/HISTORY.md](../../evals/results/HISTORY.md)).

Czego brakuje:

- Monitoringu z alertami: czy strona działa, ile zostało kredytów Tavily i budżetu modelu (#75).
- Procedury korekt. Nie ustaliliśmy, kto poprawia błędną odpowiedź, w jakim czasie i gdzie wisi
  rejestr poprawek.
- Kanału zgłoszeń. Przy odpowiedzi nie ma przycisku „zgłoś błąd”.
- Trwałości. Dziennik sprawdzeń znika przy każdym wdrożeniu, bo nie ma wolumenu (#70, wolumen
  w PR #109, w `integration/r3`). Baza nie ma
  automatycznych kopii zapasowych, a serwer jest jeden, bez zapasowego ([docs/deploy.md](../deploy.md),
  sekcja „Known limits”).

Szacunek: 5-7 osobodni (zgłoszenia i rejestr korekt: 2-3, monitoring i alerty: 1-2, #70 i kopie
zapasowe: 1, opis procedury: 1). Drugi serwer zależy od infrastruktury MSZ.

## Etap 5. Nowe kanały, języki i źródła, ale dopiero po walidacji regresji

Co już jest:

- Kanały są oddzielone od weryfikacji. Bot Discord nie ma własnej logiki i wysyła tekst do tego
  samego `POST /api/checks` co strona ([prawdowid/discord_bot.py](../../prawdowid/discord_bot.py)).
  Ewaluacja umie zmierzyć zgodność obu kanałów (`PRAWDOWID_EXTRA_CHANNELS=discord`).
- Źródła działają jak wtyczki, każde z własnym limitem czasu ([prawdowid/pipeline.py](../../prawdowid/pipeline.py)).
  Lista domen wyszukiwarki jest w kodzie i w dokumentacji, a test pilnuje, żeby się nie rozjechały
  ([tests/test_websearch.py](../../tests/test_websearch.py)).
- Lokalna kontrola przed `git push`. Hook uruchamia ruff i pytest, wymaga akceptacji agenta-sędziego
  dla wypychanego commita, a przy zmianie kodu produktu evalu na tym samym stanie kodu (od pierwszego
  evalu w danym klonie). Słabe metryki blokują dopiero
  zgłoszenie końcowe (`HN_FINAL=1`: pełny eval, wszystkie metryki powyżej progów), przy zwykłym
  pushu hook tylko ostrzega ([.githooks/pre-push](../../.githooks/pre-push)). To jeszcze nie jest
  walidacja regresji, o którą prosi brief: brakuje CI (etap 1) i progów uzgodnionych z MSZ.

Czego brakuje:

- Adapterów WhatsApp i SMS. Nie zbudowaliśmy ich, a przy wdrożeniu trzeba będzie podać opłaty operatora.
- Innych języków. Interfejs i zapytania są po polsku. Angielskie zapytania do źródeł
  międzynarodowych to #89.
- Progów jakości uzgodnionych z MSZ i zbioru testowego, którego zespół nie widzi (#91).
- Bota Discord na produkcji (#59).

Szacunek: 2-4 osobodni na kanał, bez czasu weryfikacji konta biznesowego u operatora. Do tego #89:
1-2 osobodni. Zbiór ukryty przygotowuje MSZ.

## Razem

Około 24-35 osobodni pracy zespołu przy jednym nowym kanale (WhatsApp albo SMS), 26-39 przy obu
(szacunek). Do tego czas po stronie MSZ: przegląd bezpieczeństwa, DPIA, audyt dostępności,
konsultacje i sam pilotaż.

## Tekst na slajd

Tytuł slajdu: Pilotaż z MSZ w pięciu etapach

| Etap | Już jest | Brakuje |
|---|---|---|
| 1. Odtworzenie i przegląd | `make up`, 547 testów, eval z metrykami jury, rejestr ryzyk | licencji repo, SBOM, CI |
| 2. 4-6 tygodni na zamkniętym korpusie | 1158 dokumentów z 11 domen, wyszukiwanie lokalne | pomiaru korpusu (#74 jest w `integration/r3`), kolejki eksperta (#79) |
| 3. Red team, dane, dostępność | scenariusz E, maskowanie, 30 dni, usuwanie sesji | zewnętrznego red teamu, DPIA, audytu WCAG, konsultacji |
| 4. Ograniczone wdrożenie | faktczyfejk.pl na serwerze w UE, dziennik sprawdzeń | alertów, procedury korekt, przycisku „zgłoś błąd” |
| 5. Nowe kanały i źródła | bot Discord w kodzie, na tym samym API; hook z testami i kontrolą evalu przed pushem | bota na produkcji (#59), WhatsApp i SMS, CI, progów uzgodnionych z MSZ |

Pod tabelą: „Tryb wsparcia decyzji: odpowiedź do publikacji zatwierdza człowiek. Start: bezpieczeństwo
podróży, 239 profili krajów z Odyseusza.”

Przypis: „Praca zespołu: około 24-35 osobodni przy jednym nowym kanale (szacunek). Szczegóły:
docs/submission/pilot.md”
