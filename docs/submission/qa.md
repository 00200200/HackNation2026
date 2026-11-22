# Pytania jury: przygotowanie do etapu II

Dwadzieścia pytań, które jury może zadać po pitchu, z odpowiedziami opartymi wyłącznie na tym, co
jest w repozytorium. Najpierw zdanie do powiedzenia na głos, potem szczegóły na dopytanie i linki.
Stan: build `integration/r4` (zawiera `integration/r3`), 22.11.2026; zdania o `main` opisują starszy build. Metryki pochodzą z
[evals/results/HISTORY.md](../../evals/results/HISTORY.md). Zanim zacytujesz którąś,
przeczytaj [docs/eval-notes.md](../eval-notes.md). Numery z krzyżykiem to zgłoszenia w
[repozytorium](https://github.com/00200200/HackNation2026/issues).

## Jakość i prawda

### 1. Skąd wiecie, że model nie zmyśla?

Krótko: model nie wydaje werdyktu. Werdykt liczy kod, i to tylko z cytatów, które znaleźliśmy w
źródle słowo w słowo.

Szczegóły: Claude wyodrębnia twierdzenia. Drugi model, sędzia, oznacza fragmenty źródeł jako
potwierdzające, przeczące albo dające kontekst i podaje dokładny cytat. Kod przyjmuje cytat tylko
wtedy, gdy ma co najmniej trzy słowa i występuje w tytule albo we fragmencie wskazanego dokumentu
jako ciągły tekst. Wielkość liter, cudzysłowy i spacje nie mają znaczenia, ale liczba musi się
zgadzać co do znaku. Na ekranie pokazujemy tekst źródła, nie parafrazę modelu (`verify_quotes`,
`find_quote`). Werdykt
wylicza `decide()` według tabeli reguł. Strona podana do sprawdzenia nie może być dowodem samej
siebie. Gdy dowodów brak, odpowiedź brzmi „brak wystarczających dowodów”.

Czego nie wiemy: dosłowny cytat w źródle nie dowodzi, że źródło potwierdza twierdzenie. Poprawności
cytatów jeszcze nie zmierzyliśmy (#62). Ręcznej kontroli co najmniej 10 cytatów, której wymagamy
przed zgłoszeniem końcowym, w repozytorium jeszcze nie ma.

Źródła: [prawdowid/judge.py](../../prawdowid/judge.py),
[ADR 0001](../adr/0001-evidence-retrieval-and-verdict.md), [risks.md](risks.md),
[.claude/skills/prawdowid-eval/SKILL.md](../../.claude/skills/prawdowid-eval/SKILL.md),
[#62](https://github.com/00200200/HackNation2026/issues/62).

### 2. Czym to się różni od zapytania czatbota?

Krótko: czatbot odpowiada z pamięci. My odpowiadamy z przypisem albo wcale.

Szczegóły: każde twierdzenie z dowodami dostaje źródła z tytułem, wydawcą, datą publikacji i pobrania, linkiem
i cytatem, o ile je znamy. Materiał źródłowy jest oddzielony od wyjaśnienia modelu, które ma osobną etykietę.
Werdykt ustala reguła w kodzie, a nie model. Opinia albo prognoza dostaje „nie podlega weryfikacji”,
a twierdzenie bez dowodów „brak wystarczających dowodów”. Każde sprawdzenie zostawia zamaskowany wpis
w dzienniku, więc da się je potem prześledzić.

Źródła: [README](../../README.md#how-it-works), [frontend/public/app.js](../../frontend/public/app.js),
[prawdowid/judge.py](../../prawdowid/judge.py), [prawdowid/checklog.py](../../prawdowid/checklog.py).

### 3. Kto decyduje, co jest prawdą?

Krótko: czytelnik. My pokazujemy podstawy, czyli źródło, cytat i to, czego nie ustaliliśmy.

Szczegóły: brief w rozdziale 9 mówi, że narzędzie ma wspierać świadomą ocenę, a nie być
automatycznym „sędzią prawdy”. Tak to zapisaliśmy w decyzjach zespołu 21.11. Reguła: strona sporu
liczy się, gdy popiera ją jedno źródło urzędowe, pierwotne albo fact-checkingowe, albo dwa niezależne
źródła, zawsze ze sprawdzonym cytatem. Gdy obie strony mają takie poparcie, wynik to „brak
wystarczających dowodów” i pokazujemy konflikt. Gdy źródło nazywa brakujący kontekst, wynik to
„wprowadzające w błąd”. Progi tych reguł to nasze założenia, jeszcze nie dostrojone. W pilotażu każdą
odpowiedź do publikacji zatwierdzi człowiek. Dziś takiego kroku nie ma.

Źródła: [WORKLOG.md](../../WORKLOG.md) (sekcja „Decisions”), [prawdowid/judge.py](../../prawdowid/judge.py),
[pilot.md](pilot.md).

### 4. Kto wybrał źródła? Czy to nie jest stronnicze?

Krótko: my, według spisanych reguł, i obie listy są jawne. To wciąż nasz wybór, a status części
fact-checkerów dopiero potwierdzamy.

Szczegóły: list są dwie. Wyszukiwarka zwraca tylko strony z domen na liście `ALLOWLIST`: polskie
urzędy, instytucje UE, NATO i WHO, trzech fact-checkerów (Konkret24, FakeNews.pl, AFP Sprawdzam) na `main`, agencję PAP i EUvsDisinfo jako bazę znanych narracji. Każda domena ma typ: urzędowe, fact-checking,
agencja prasowa albo baza narracji. Status IFCN albo EFCSN tych trzech fact-checkerów jest do
potwierdzenia na listach obu sieci ([docs/sources.md](../sources.md)). Do korpusu przyjmujemy urzędy
polskie i unijne oraz fact-checkerów, których status odczytaliśmy na stronie sieci, z datą odczytu.
21.11 odczytaliśmy dwa: Pravda jest zweryfikowanym członkiem EFCSN do 23.02.2028, a Demagog do
25.05.2027. Decyzja z 21.11 brzmiała: Demagoga bierzemy tylko przez Google Fact Check. W `integration/r3` (#76) lista wyszukiwarki ma też demagog.org.pl, ale tylko jako fragmenty z wyszukiwarki, bo jego serwis odpowiada naszemu serwerowi 403, oraz pravda.org.pl i oko.press (media). Reszta tego pytania opisuje `main`. Dowody od tego
samego wydawcy, z tym samym cytatem albo z tej samej agencji prasowej liczą się jako jedno źródło.
EUvsDisinfo nigdy sam nie rozstrzyga.

Słabe strony: listy to decyzja zespołu i nikt z zewnątrz nie badał ich różnorodności. Część
fact-checkingowa korpusu to 15 rekordów Pravdy. Dwóch z trzech fact-checkerów z listy wyszukiwarki,
Konkret24 i AFP Sprawdzam, blokuje nasz serwer (pytanie 6).

Źródła: [prawdowid/websearch.py na main](https://github.com/00200200/HackNation2026/blob/1aa173f/prawdowid/websearch.py#L52), [na integration/r3](../../prawdowid/websearch.py), [docs/sources.md](../sources.md),
[corpus/catalog.yaml](../../corpus/catalog.yaml), [docs/corpus.md](../corpus.md), [risks.md](risks.md).

### 5. Jak dodajecie i wykluczacie źródła?

Krótko: przez jeden plik z regułami, w którym każda decyzja ma powód i datę.

Szczegóły: [corpus/catalog.yaml](../../corpus/catalog.yaml) ma reguły przyjęcia, aktualizacji i
wykluczenia. Źródło wypada, gdy robots.txt go zabrania, gdy strona odrzuca skrypty, gdy jest
niedostępna dłużej niż jej okres odświeżania, gdy traci status fact-checkera albo gdy warunki
przestają pozwalać na fragment. Może też wypaść decyzją zespołu, jak Demagog 21.11. Wykluczone wpisy
zostają w katalogu z powodem i datą. Pojedynczy dokument usuwamy przez `removed_urls` i przebudowę
korpusu. Okres odświeżania wynosi od godziny (ostrzeżenia IMGW) do 30 dni (akty UE). Domenę w
wyszukiwarce dodajemy w kodzie i w [docs/sources.md](../sources.md) w jednym commicie, a test nie
przejdzie, gdy lista w dokumentacji się rozjedzie. Hook przed `git push` uruchamia ruff i pytest, a
przy zmianie kodu wymaga evalu zrobionego na tym samym stanie kodu (od pierwszego evalu w danym
klonie). Słabe metryki blokują dopiero
zgłoszenie końcowe (`HN_FINAL=1`), przy zwykłym pushu hook tylko ostrzega. Automatycznego
odświeżania na serwerze jeszcze nie ma (#90).

Źródła: [docs/corpus.md](../corpus.md), [tests/test_websearch.py](../../tests/test_websearch.py),
[.githooks/pre-push](../../.githooks/pre-push), [#90](https://github.com/00200200/HackNation2026/issues/90).

### 6. Polscy fact-checkerzy blokują wasz serwer. Co wtedy?

Krótko: nie obchodzimy blokady. W buildzie `integration/r3` bierzemy tylko to, co zwraca
wyszukiwarka, i oznaczamy to jako fragment z wyników (#95). Na `main`, bez #95, takie trafienie
jeszcze wypada.

Szczegóły: w nocy 22.11 z naszego serwera konkret24.tvn24.pl, sprawdzam.afp.com i
demagog.org.pl odpowiadały 403, i z naszym user agentem, i z przeglądarkowym, a oko.press i
pravda.org.pl odpowiadały 200 (#95). Brief zabrania obchodzenia zabezpieczeń, a nasze pobieranie nigdy nie
omija odpowiedzi 401, 403, 429 ani blokady botów. Dziś trafienie, którego strony nie da się pobrać,
po prostu wypada na `main`, choć wyszukiwarka zwróciła jego fragment. W `integration/r3` (#95) ten
fragment zostaje, ale tylko gdy strona odmawia, nie odpowiada na czas, jest za duża albo nie da
się jej odczytać. Gdy robots.txt zabrania pobrania, strona zniknęła albo wymaga logowania lub
płatności, nie bierzemy nawet fragmentu.

Zasadę na ten przypadek zatwierdził Michał 22.11.2026 ([WORKLOG](../../WORKLOG.md), sekcja
„Decisions”). Gdy nie możemy pobrać strony sami (blokada,
przekroczony czas, za duży plik, nieobsługiwany typ), dowodem staje się tytuł i fragment zwrócone
przez wyszukiwarkę. Odpowiedź oznacza go jako „fragment z wyników wyszukiwarki; strona nie pozwala
na pobranie”. Cytat sprawdzamy na tym fragmencie jak na każdym innym. Pełnej treści takiej strony nie
zapisujemy i nigdy nie pobieramy jej inną drogą. Stan: #95 jest w `integration/r3` i nie
wszedł jeszcze do `main`. Po stronie jakości: nie mierzyliśmy jeszcze, jak często taki fragment
wystarcza do cytatu.

Źródła: [#95](https://github.com/00200200/HackNation2026/issues/95),
[#76](https://github.com/00200200/HackNation2026/issues/76), [docs/sources.md](../sources.md),
[prawdowid/safefetch.py](../../prawdowid/safefetch.py).

### 7. Co, jeśli źródło jest objęte sankcjami UE?

Krótko: status źródła nigdy nie decyduje o werdykcie. Planujemy osobną, neutralną notatkę, ale
jeszcze jej nie zbudowaliśmy.

Szczegóły: brief zabrania rozstrzygania prawdziwości na podstawie statusu źródła, także sankcji UE.
ADR 0001 proponuje notatkę z aktem prawnym i datą sprawdzenia, braną tylko z urzędowego źródła UE.
Notatka nie zmienia werdyktu ani jego siły (#81). Media objęte sankcjami nie mogą dziś być dowodem,
bo lista domen wyszukiwarki zawiera tylko urzędy, instytucje UE i międzynarodowe, fact-checkerów,
PAP i EUvsDisinfo (w `integration/r3` także OKO.press jako media).

Źródła: [ADR 0001](../adr/0001-evidence-retrieval-and-verdict.md), sekcje 5 i 6,
[prawdowid/websearch.py](../../prawdowid/websearch.py),
[#81](https://github.com/00200200/HackNation2026/issues/81).

### 8. Co, jeśli tekst albo strona źródłowa zawiera polecenia dla modelu?

Krótko: traktujemy je jak dane. Nie wykonujemy ich, mówimy o tym użytkownikowi i zapisujemy
zdarzenie. Dla poleceń w pobranych stronach to stan buildu `integration/r3` (#61, PR #72), nie
`main`.

Szczegóły: instrukcje systemowe są oddzielone od danych. Dwa detektory: stałe wzorce w kodzie i
flaga od modelu, który wyodrębnia twierdzenia. Zdarzenie bezpieczeństwa zapisujemy bez treści ataku,
a strona pokazuje: „W treści są zwroty, które wyglądają na polecenia dla modelu. Nie wykonaliśmy ich
i sprawdziliśmy resztę”. W buildzie `integration/r3` pobrane źródła są też przeglądane w kodzie
tymi samymi wzorcami, niezależnie od modeli, a strona pokazuje wtedy: „W źródłach są zwroty, które
wyglądają na polecenia dla modelu. Nie wykonaliśmy ich i sprawdziliśmy resztę”. Polecenie, które
sędzia znajdzie w pobranej stronie, też trafia do zdarzeń, z miejscem `source` (zdarzenie bez
treści ataku, `detector=model`). Na `main`, bez PR #72, działa tylko to drugie.

Wyniki z [HISTORY.md](../../evals/results/HISTORY.md): odporność na injection 0,000 w szybkim
przebiegu na `95e6177`, 0,571 w pełnym przebiegu na `8c6f396` (ten przebieg jest zniekształcony) i
1,000 w pełnym przebiegu na `ca48b84` (75 przypadków, E05-E15 pominięte), przy progu 0,90. Ten
przebieg ma macro-F1 0,803, ale `end_to_end` 0,973 i `moderator_loop` 0,000 nie spełniają progów, więc
całość nadal nie przechodzi. Wzorce pisaliśmy, znając pierwsze trzy przypadki E, więc potrzebujemy nowych.
Przypadki z poleceniem ukrytym w stronie mają fixtures w `integration/r3` (#94), ale nie
uruchamialiśmy na nich evalu. Pełny przebieg na `ca48b84` pominął E05-E15 (11 przypadków), bo brakowało publicznego adresu
strony z fixture (`PRAWDOWID_FIXTURE_BASE`), więc wynik 1,000 dotyczy 7 przypadków E. Sprawdzanie pobranych źródeł (PR #72) też
jest tylko w `integration/r3`.

Źródła: [risks.md](risks.md), [prawdowid/verifier.py](../../prawdowid/verifier.py),
[frontend/public/app.js](../../frontend/public/app.js), [WORKLOG.md](../../WORKLOG.md) (wpis do #15),
[#94](https://github.com/00200200/HackNation2026/issues/94),
[PR #72](https://github.com/00200200/HackNation2026/pull/72).

### 9. Co się dzieje, gdy źródło nie działa albo skończy się limit?

Krótko: mówimy, co nie zadziałało. Gdy padną wszystkie źródła albo model, werdyktu nie ma. Gdy
padnie źródło, które może rozstrzygnąć, a dowodów nie starcza, werdyktu też nie ma, ale to reguła
z #60 z buildu `integration/r3`. Na `main` jest tu jeszcze luka i mówimy o niej wprost.

Szczegóły: każde źródło ma własny limit czasu. Google Fact Check ma 15 s, EUvsDisinfo 5 s w potoku,
jedno zapytanie do wyszukiwarki 10 s, pobranie strony 8 s, a całe sprawdzenie 40 s (w
`integration/r3`, #63; na `main` 25 s). Twierdzenie,
którego wszystkie źródła padły, dostaje „nie sprawdzono” z powodem. Tak samo, gdy skończy się czas
albo nie odpowie model-sędzia. Brak klucza do modelu albo jego błąd przy wyodrębnianiu twierdzeń daje
komunikat techniczny. Jedenaste zapytanie w ciągu minuty dostaje komunikat „Wysłano za dużo zapytań w
krótkim czasie”. Eval ma 4 przypadki J. Na `main` dwa (FC-J01, FC-J02) pomijamy, a dwa pozostałe (J01, J02)
liczymy bez zasymulowanej awarii, bo przełącznika awarii jeszcze nie ma (#60). W `integration/r3` jest
przełącznik ([prawdowid/faults.py](../../prawdowid/faults.py)) i FC-J01 oraz FC-J02 działają z `simulate`.

Luka (#60), zamknięta w buildzie `integration/r3` (PR #109), na `main` jeszcze otwarta: gdy
padnie tylko część źródeł, a reszta nic nie znajdzie, `main` zwraca „brak wystarczających dowodów”.
W ograniczeniach odpowiedzi stoi wtedy, które źródło nie odpowiedziało, ale sam werdykt wygląda jak
brak dowodów, a brief w scenariuszu J tego zabrania. Przykład: Tavily odmawia, bo skończyły się
kredyty, co kod traktuje jak każdą awarię wyszukiwarki, a Google Fact Check odpowiada, że nic nie
znalazł. W `integration/r3`, gdy padnie źródło, które może rozstrzygnąć (Fact Check albo
wyszukiwarka, dla twierdzeń rządowych także wyszukiwarka gov.pl), a dowodów nie starcza,
twierdzenie dostaje „nie sprawdzono”. Korpus nie liczy się jako źródło, które odpowiedziało.

Źródła: [prawdowid/pipeline.py](../../prawdowid/pipeline.py),
[prawdowid/websearch.py](../../prawdowid/websearch.py),
[prawdowid/factcheck.py](../../prawdowid/factcheck.py), [prawdowid/app.py](../../prawdowid/app.py),
[docs/reference.md](../reference.md#configuration), [#60](https://github.com/00200200/HackNation2026/issues/60),
[#75](https://github.com/00200200/HackNation2026/issues/75),
[PR #109](https://github.com/00200200/HackNation2026/pull/109).

### 10. Dlaczego tak często „nie udało mi się potwierdzić”?

Krótko: wolimy przyznać, że nie wiemy, niż zgadywać. Ale część tych odpowiedzi to nasz błąd w
pobieraniu stron i właśnie go naprawiamy.

Szczegóły: brief wymaga poprawnego wstrzymania się od oceny w co najmniej 80% przypadków bez
dowodów. Szybki przebieg na `95e6177` dał 1,000, ale tylko dlatego, że wszystkie 9 odpowiedzi
brzmiały „brak wystarczających dowodów” (macro-F1 0,100). Zniekształcony pełny przebieg na `8c6f396`
dał 0,583, a pełny przebieg na `ca48b84` 0,917 ([HISTORY.md](../../evals/results/HISTORY.md)). Przy
tak małej liczbie przypadków bez dowodów to wciąż mało na wniosek o zbiorze ukrytym. Do tego w szybkim przebiegu na stagingu
22.11 (`75c1e20`) wyszukiwarka znajdowała strony, a potem je odrzucała: 102, bo
robots.txt odpowiadał 403 (czytane jako zakaz wszystkiego), 36 bez tekstu, tytułu albo daty, 17 po
przekroczeniu 8 s, 8 większych niż 2 MB i 5 plików PDF (#95). Poprawki są w #95 (w `integration/r3`, jeszcze nie w `main`). Pełny przebieg na `ca48b84`, który je
zawiera, dał macro-F1 0,803 wobec 0,278 w szybkim przebiegu na `edd34a5`, przed #95. To dwa przebiegi na
różnych liczbach przypadków (75 i 10), więc nie rozdzielamy, ile dała sama poprawka #95, a ile
pozostałe zmiany. Korpus urzędowy jest w `integration/r3` podpięty do sprawdzania (#74), a jego wpływu
osobno nie mierzyliśmy.

Źródła: [HISTORY.md](../../evals/results/HISTORY.md),
[#95](https://github.com/00200200/HackNation2026/issues/95),
[#74](https://github.com/00200200/HackNation2026/issues/74).

### 11. Jakie macie wyniki i czy utrzymacie je na zbiorze ukrytym?

Krótko: żaden zapisany przebieg nie spełnia wszystkich progów i tego nie ukrywamy. Najlepszy, pełny
przebieg na `ca48b84`, ma macro-F1 0,803 przy progu 0,75, ale dwie metryki poniżej progu. Runner zapisuje
każdy przebieg do HISTORY.md i `evals/results/history/`; nie zachowaliśmy pliku JSON z przebiegu
stagingowego (3,96 USD za 100) ani z pomiaru z 21.11 (5,25 USD za 100), a część wierszy HISTORY.md jest
odtworzona.

Szczegóły: nasz zestaw to na `main` 73 przypadki (41 w zestawie A-J i 32 w zestawie FC), a w `integration/r3` 86 (54 w A-J i U oraz 32 w FC).
Rozkład scenariuszy na `main`: A 23, B 10, C 6, D 8, E 7, G 6, H 2, I 7, J 4; w `integration/r3`: A 23, B 10, C 6, D 8,
E 18, G 6, H 2, I 7, J 4, U 2. Etykiety pochodzą z ocen Demagoga, Konkret24,
EUvsDisinfo i stron urzędowych, a przy każdym przypadku zapisaliśmy, skąd jest etykieta. Wyjątek to
przypadki D01-D04 oraz H01 i H02: plotki wymyślone przez zespół, o których nikt nie pisał, więc
poprawna odpowiedź to brak dowodów. Zapisane przebiegi: szybki na `95e6177` dał macro-F1 0,100, abstencję
1,000 i odporność na injection 0,000, przy czym wszystkie 9 odpowiedzi brzmiały „brak wystarczających
dowodów”. Pełny na `8c6f396` (71 przypadków) dał macro-F1 0,498,
abstencję 0,583, odporność na injection 0,571 i medianę 18,2 s. Ten wiersz odtworzyliśmy bez pliku
JSON, a sam przebieg zniekształciły timeouty Anthropic i zbyt ciasny budżet 25 s.

Najnowszy, pełny przebieg na `ca48b84` (22.11, `integration/r3`, 75 ocenionych przypadków z 86,
E05-E15 pominięte bez publicznego adresu fixture): macro-F1 0,803 (próg 0,75), citation_coverage
1,000 (0,95), citation_correctness 1,000 (0,85), abstencja 0,917 (0,80), odporność na injection 1,000
(0,90), mediana 17,8 s (30 s), zgodność kanałów 1,000, koszt 4,27 USD za 100 sprawdzeń. Poniżej progu:
`end_to_end` 0,973 (wymagane 1,000) i `moderator_loop` 0,000 (1,000; ten przebieg powstał przed pętlą moderatora, #79).
Wynik ogólny: nie przechodzi. `citation_correctness` sprawdza tylko, czy cytat występuje w źródle, a
nie czy dobrze wspiera werdykt. Zmierzyliśmy ją na 1,000, ale to tylko warunek
konieczny: nie wiemy jeszcze, czy cytat wspiera tezę ani czy korpus poprawia odpowiedzi. Zgodność kanałów
1,000 pokazuje, że wspólna pamięć wyników (#59, 30 minut) oddaje na Discordzie zapisaną odpowiedź (te
odpowiedzi trwały 0,1-0,2 s, na stronie 12-35 s), a nie że dwa niezależne sprawdzenia się zgadzają.
Wiersz jest w HISTORY.md razem z plikiem JSON
`evals/results/history/20261122T021757.182695Z-ca48b84-full.json`; oba są w repozytorium. Przebieg na commicie zgłoszenia: [z #16].

Zbioru ukrytego nie znamy. Zasada: żadnych przypadków ani odpowiedzi z evalu w promptach i w logice
weryfikacji (w `prawdowid/` nie ma tekstu żadnego przypadku). Wyjątek jest na stronie: przycisk
„Polska w NATO od 1999” wkleja pytanie z przypadków A01 i J02, które jest też początkiem E01.
Kontrola przecieku i wydzielony zbiór testowy są otwarte (#91). Nie obiecujemy liczby, której nie
zmierzyliśmy.

Źródła: [evals/cases.jsonl](../../evals/cases.jsonl), [HISTORY.md](../../evals/results/HISTORY.md),
[docs/eval-notes.md](../eval-notes.md),
[.claude/skills/prawdowid-eval/SKILL.md](../../.claude/skills/prawdowid-eval/SKILL.md),
[#91](https://github.com/00200200/HackNation2026/issues/91),
[#16](https://github.com/00200200/HackNation2026/issues/16).

## Dane, koszty, wdrożenie

### 12. Co z danymi osobowymi i RODO?

Krótko: dane maskujemy, zanim tekst trafi do modelu, zapis trzymamy 30 dni, a użytkownik może go
usunąć jednym przyciskiem. Analizy RODO z inspektorem ochrony danych MSZ jeszcze nie ma.

Szczegóły: maskujemy e-maile, numery kont IBAN/NRB (suma kontrolna mod 97), karty (algorytm Luhna),
PESEL (suma kontrolna) i telefony, przed modelem i w każdym logu. Dziennik trzyma zamaskowany wpis
30 dni (`RETENTION_DAYS`). Przycisk „Usuń moje sprawdzenia” wywołuje `DELETE /api/sessions/{id}`.
Tekstu stron z linków nie zapisujemy, a strona spod linku widzi adres naszego serwera, nie
użytkownika. Pod polem tekstowym piszemy: „Nie wklejaj danych osobowych, sprawdzenia trzymamy do 30
dni”. Serwer stoi w Niemczech.

Luki: nie maskujemy imion i adresów, numerów dowodów, paszportów i części formatów telefonu (#82).
Discord nie ma polecenia usuwania, a odpowiedzi bota są widoczne na kanale. Logi `stdout` Dockera są
poza retencją. Gdzie dane przetwarzają dostawcy, jest UNCONFIRMED (#85). Nie ma DPIA ani umów
powierzenia, to etap 3 pilotażu.

Źródła: [prawdowid/privacy.py](../../prawdowid/privacy.py), [docs/privacy.md](../privacy.md),
[risks.md](risks.md), [frontend/public/index.html](../../frontend/public/index.html),
[#82](https://github.com/00200200/HackNation2026/issues/82),
[#85](https://github.com/00200200/HackNation2026/issues/85).

### 13. Ile to kosztuje?

Krótko: obywatel płaci zero. Nas jedno sprawdzenie kosztuje około 33 groszy: modele według pełnego przebiegu na `ca48b84`, a kredyty
Tavily według pomiaru z 21.11, a serwer z domeną około 43 zł miesięcznie.

Szczegóły: modele to 0,0427 USD za sprawdzenie: pełny przebieg na `ca48b84` (75 przypadków, kod
`integration/r3` z #88, #95 i #74; średnia z 71 odpowiedzi z ceną; cztery symulowane awarie nie wysyłają zapytań do modelu i są pominięte;
wiersz w HISTORY.md; kod sprzed #106). Wcześniejsze pomiary: 4,91 USD za 100 na `edd34a5` (Opus, przed #95) i 3,96 USD za
100 ze stagingu (bez wiersza w HISTORY.md i pliku JSON). Tavily dokłada około 4,9 kredytu (wpis z 21.11 w
WORKLOG, sprzed #106; dziś to około 4 wyszukiwań na twierdzenie bez ponawiania). Konto jest na planie Researcher z opłatą za zużycie: 1000 kredytów miesięcznie za darmo,
potem 0,008 USD za kredyt, limit konta podniesiony 22.11 do 4000 kredytów (czy z darmowymi:
UNCONFIRMED). Na 1000 sprawdzeń wychodzi 73,70 USD, czyli 299 zł (81,70 USD, czyli 332 zł, gdy darmowe
kredyty zużyją testy). Ten limit starcza na 820 do 1025 sprawdzeń, zależnie od tego, czy wlicza darmowe kredyty (UNCONFIRMED), więc
1000 mieści się tylko przy górnej granicy. Kwoty dla 1000 sprawdzeń to szacunki: koszt modeli z jednego pełnego przebiegu, kredyty Tavily z pomiaru na 8 przypadkach.
Abonamentowe stawki Tavily (do 0,005 USD za kredyt w planie Growth za 500 USD miesięcznie) nie
obniżają tego rachunku przy takim ruchu. Koszty stałe: VPS-2 od 37,85 zł brutto miesięcznie,
domena 58,99 zł rocznie przy odnowieniu, bot Discord 0 zł ponad serwer. Koszt 100 testów to 4,27 USD za modele
(`ca48b84`) plus około 3,90 USD za Tavily (szacunek ze średniej historycznej, nie górna granica).
Kredyty Tavily z pełnego przebiegu dopiero policzymy (#16).

Źródła: [cost.md](cost.md), [HISTORY.md](../../evals/results/HISTORY.md), [WORKLOG.md](../../WORKLOG.md).

### 14. Co przy 10 i 100 razy większym ruchu?

Krótko: koszt rośnie liniowo, a rachunek to prawie wyłącznie tokeny modeli i kredyty wyszukiwarki.
Serwer to poniżej 2%. Przepustowości jednego serwera jeszcze nie zmierzyliśmy.

Szczegóły: przy umownych 10 000 sprawdzeń miesięcznie wychodzi około 3328 zł, przy 100 000 około
33 191 zł plus kolejne serwery (Tavily po 0,008 USD za kredyt, bez abonamentu). Modele to od 52 do
58% kosztów zmiennych. Podziału kosztu modeli na wyodrębnianie, ranking i sędziego nie zmierzyliśmy, więc nie podajemy, ile
da tańszy model. Od #88 wyodrębnianie domyślnie idzie na Sonnet 5.5; pomiary 4,91 USD za 100 (`edd34a5`)
i 4,27 USD (`ca48b84`) dotyczą różnych zestawów przypadków i różnego kodu, więc nie są czystym efektem tej
zmiany. Dziś backend to jeden proces z limitem zapytań w pamięci,
na jednym serwerze bez zapasowego. Test obciążeniowy to #88.

Źródła: [cost.md](cost.md), [Dockerfile](../../Dockerfile), [docs/deploy.md](../deploy.md),
[#88](https://github.com/00200200/HackNation2026/issues/88).

### 15. Czy nie uzależniacie MSZ od jednego dostawcy? Gdzie są przetwarzane dane?

Krótko: inny model Anthropic to jedna zmienna środowiskowa. Inny dostawca modeli to jego pakiet i
przebudowa obrazu backendu, a inna wyszukiwarka to jedna funkcja. Całego systemu przebudowywać nie
trzeba. Serwer stoi w Niemczech, ale gdzie dane przetwarzają dostawcy, jeszcze nie potwierdziliśmy.

Szczegóły: modele wybieramy przez PydanticAI, a każdy etap ma swoją zmienną z nazwą modelu:
`PRAWDOWID_MODEL` (wyodrębnianie), `PRAWDOWID_JUDGE_MODEL` (sędzia), `PRAWDOWID_RERANK_MODEL`
(ranking) i `PRAWDOWID_IMAGE_MODEL` (odczyt obrazu, domyślnie model wyodrębniania). Inny model
Anthropic to zmiana tej zmiennej i restart. [compose.yaml](../../compose.yaml)
przekazuje do kontenera tylko `PRAWDOWID_MODEL` i `PRAWDOWID_IMAGE_MODEL`, więc
dwie pozostałe trzeba dopisać w nadpisaniu Compose. Inny dostawca, na przykład Mistral, potrzebuje
swojego pakietu. Instalujemy tylko `pydantic-ai-slim[anthropic,mcp]` ([pyproject.toml](../../pyproject.toml)),
a bez pakietu dostawcy PydanticAI zgłasza ImportError i każde sprawdzenie kończy się komunikatem
technicznym. Trzeba więc dodać extra i klucz dostawcy, a potem przebudować obraz backendu. Tej drogi
nie testowaliśmy. Wyszukiwarka siedzi za kontraktem `SearchProvider`, a zamienniki (Exa, Brave)
porównaliśmy przy wyborze dostawcy (decyzja do #7 w WORKLOG). W sprawdzeniu korpus przeszukuje BM25 w pamięci
(`prawdowid/corpus_bm25.py`). Osobny indeks pgvector z embeddingami e5-large (licencja MIT) jest
przygotowany, ale sprawdzanie go nie używa. Serwer: OVHcloud, Limburg, Niemcy.

Czego jeszcze nie ma: nie pokazaliśmy działania na modelu przetwarzanym w UE. Gdzie przetwarzają
dane Anthropic, Google, Tavily i EUvsDisinfo, jest UNCONFIRMED. W lutym 2026 Nebius ogłosił
przejęcie Tavily; czy transakcja się zamknęła i gdzie Tavily przetwarza dane, też jest UNCONFIRMED.
Ani Tavily, ani Exa, ani Brave nie opisuje przetwarzania w EOG (#85).

Źródła: [prawdowid/verifier.py](../../prawdowid/verifier.py), [pyproject.toml](../../pyproject.toml),
[compose.yaml](../../compose.yaml),
[prawdowid/rerank.py](../../prawdowid/rerank.py), [prawdowid/judge.py](../../prawdowid/judge.py),
[prawdowid/websearch.py](../../prawdowid/websearch.py), [docs/deploy.md](../deploy.md),
[docs/privacy.md](../privacy.md), [WORKLOG.md](../../WORKLOG.md),
[#85](https://github.com/00200200/HackNation2026/issues/85).

### 16. Dlaczego Discord? Jak podłączyć WhatsApp albo SMS?

Krótko: brief dopuszcza Discorda, jest darmowy i jury sprawdzi go bez numerów testowych. Każdy
kolejny kanał to cienki adapter do tego samego API.

Szczegóły: organizator nie daje kont, numerów testowych ani kluczy. Bot z komendą `/sprawdz` nie ma
własnej logiki: wysyła tekst do `POST /api/checks` z nagłówkiem `X-Channel: discord` i formatuje
odpowiedź. WhatsApp albo SMS działałyby tak samo. Webhook operatora odbiera wiadomość, adapter woła
to samo API, przycina odpowiedź do limitów kanału i ją odsyła. Nie zbudowaliśmy tego, a opłaty
operatora za wiadomość trzeba będzie podać użytkownikom. Kwot nie znamy, dopóki nie wybierzemy
operatora. Stan bota na produkcji: #59 i PR #73. Wszyscy użytkownicy Discorda dzielą jeden limit 10
zapytań na minutę, bo bot ma jeden adres IP.

Źródła: [prawdowid/discord_bot.py](../../prawdowid/discord_bot.py), [compose.yaml](../../compose.yaml),
[#59](https://github.com/00200200/HackNation2026/issues/59),
[PR #73](https://github.com/00200200/HackNation2026/pull/73).

### 17. Czy to jest dostępne dla osób z niepełnosprawnościami?

Krótko: projektujemy pod WCAG 2.2 AA i każdą zmianę strony przegląda agent dostępności.
Zewnętrznego audytu ani testów z użytkownikami jeszcze nie było.

Szczegóły: odpowiedź jest po polsku, w formacie z przykładów organizatora: zaczyna się od „Tak.”,
„Nie.” albo „Nie udało mi się potwierdzić tej informacji.”, a każdy werdykt ma jednozdaniowe
wyjaśnienie. Strona jest responsywna. Poprawki z przeglądów są w WORKLOG: fokus zostaje na miejscu
podczas sprawdzania, błędy mają `aria-invalid`, Enter wysyła tylko z fizycznej klawiatury, długie
adresy się zawijają, obramowania pól i przycisków mają kontrast 3,9:1. Brakuje audytu WCAG z
zewnątrz i testów z osobami, które korzystają z czytnika ekranu. To etap 3 pilotażu.

Źródła: [.claude/agents/a11y-reviewer.md](../../.claude/agents/a11y-reviewer.md),
[WORKLOG.md](../../WORKLOG.md), [README](../../README.md#how-an-answer-reads), [pilot.md](pilot.md).

### 18. Gdzie jest człowiek w tej pętli?

Krótko: człowiekiem jest czytelnik, który dostaje źródła i ocenia sam, a od #79 także moderator,
który czyta kolejkę spraw. Zatwierdzania publikacji jeszcze nie ma, a w pilotażu je dodamy.

Szczegóły: brief chce, żeby przy sprawach wysokiego ryzyka i powtarzających się pytaniach bez źródeł
system powiadamiał osobę wskazaną przez administratora. Kolejkę spraw zbudowaliśmy w #79
([prawdowid/cases.py](../../prawdowid/cases.py)): sprawę zakłada sprawdzenie, w którym twierdzenie
kończy się „brak wystarczających dowodów”, które zapisało zdarzenie bezpieczeństwa albo dotyczy tematu
wysokiego ryzyka z krótkiej listy w kodzie. Działa tylko przy ustawionym `PRAWDOWID_ADMIN_TOKEN`:
bez niego sprawy nie powstają i żadna odpowiedź nie mówi o moderatorze. Odpowiedź mówi, że sprawa
trafiła do kolejki, dopiero po jej zapisaniu. Moderator czyta kolejkę jako listę JSON, bez ekranu i
bez powiadomień. Eval ma dwa przypadki H, a `moderator_loop` wynosi 0,0 w
[evals/results/latest.json](../../evals/results/latest.json), bo ten przebieg na `ca48b84` powstał
przed #79. Plan na pilotaż: widok administratora za tokenem i zatwierdzanie publikacji ze śladem
decyzji.

Źródła: [#79](https://github.com/00200200/HackNation2026/issues/79), [pilot.md](pilot.md),
[evals/cases.jsonl](../../evals/cases.jsonl).

### 19. Czy obsługujecie zrzuty ekranu i zdjęcia?

Krótko: tak, czytamy z nich tekst (#80). Nie oceniamy, czy sam obraz jest prawdziwy.

Szczegóły: strona (przycisk albo wklejenie do pola) i `/sprawdz` na Discordzie przyjmują PNG, JPEG
i WebP do 5 MB. Jedno wywołanie modelu odczytuje tekst i datę widoczną na obrazie. Potem ten tekst
idzie tą samą drogą co wklejony: wykrywanie poleceń, maskowanie danych osobowych, twierdzenia i
źródła. Odpowiedź pokazuje odczytany tekst i mówi, czego sprawdzenie obrazu nie daje: tekst odczytał
model, data na obrazie nie dowodzi daty publikacji, nie szukaliśmy wcześniejszych kopii obrazu i nie
sprawdzaliśmy, czy go przerobiono. Brief zabrania deklarowania wyszukiwania odwrotnego obrazu bez
działającego API albo jasno ograniczonej lokalnej bazy, więc go nie deklarujemy. Obrazu nie
przechowujemy, ale do odczytu trafia w całości, z metadanymi, do Anthropic. Na żywym modelu tego nie
uruchomiliśmy: jakość odczytu, czas i koszt na obraz nie są zmierzone, a przypadki F01 do F03 nie
mają jeszcze przebiegu. Dźwięku i wideo nie przyjmujemy.

Źródła: [prawdowid/image_input.py](../../prawdowid/image_input.py),
[docs/privacy.md](../privacy.md), [cost.md](cost.md#image-checks-scenario-f-80),
[#80](https://github.com/00200200/HackNation2026/issues/80).

### 20. Czy możemy to uruchomić sami?

Krótko: tak. `make up` stawia całość w Dockerze, a eval jednym poleceniem liczy te same metryki co
my. Wyniki różnią się między przebiegami: w powtórzeniach z 21.11 macro-F1 wahało się od 0,10 do 0,39
([WORKLOG](../../WORKLOG.md), wpis o Tavily), od 0,278 na `edd34a5` do 0,803 na `ca48b84`, a część wierszy
HISTORY.md odtworzyliśmy bez pliku JSON. Pełny przebieg na `ca48b84` to jeden przebieg: rozrzutu
między powtórzeniami na tym kodzie nie mierzyliśmy. Porównujcie więc z całą historią, nie z jedną liczbą.

Szczegóły: klucze wpisuje się do ignorowanego pliku `.env`. Wymagany jest tylko `ANTHROPIC_API_KEY`.
Bez kluczy do Google Fact Check, Tavily i EUvsDisinfo te źródła są zgłaszane jako niedostępne. Bez
klucza do modelu strona się otwiera, ale każde sprawdzenie kończy się komunikatem technicznym. Samo
API: `make dev`. Eval: `PRAWDOWID_URL=http://127.0.0.1:8000 uv run python -m evals.run --quick`.
Wdrożenie produkcyjne opisuje [docs/deploy.md](../deploy.md). Dokumentacja API pod `/docs` działa
lokalnie, ale na publicznym demo zwraca 404 (#87). Publiczna wersja: https://faktczyfejk.pl.

Źródła: [README](../../README.md#run), [docs/deploy.md](../deploy.md),
[.claude/skills/prawdowid-eval/SKILL.md](../../.claude/skills/prawdowid-eval/SKILL.md),
[#87](https://github.com/00200200/HackNation2026/issues/87).
