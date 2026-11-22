# Pytania jury: przygotowanie do etapu II

Dwadzieścia pytań, które jury może zadać po pitchu, z odpowiedziami opartymi wyłącznie na tym, co
jest w repozytorium. Najpierw zdanie do powiedzenia na głos, potem szczegóły na dopytanie i linki.
Stan: `main`, commit `1aa173f`, 22.11.2026. Metryki pochodzą z
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

Szczegóły: każde twierdzenie dostaje źródła z tytułem, wydawcą, datą publikacji i pobrania, linkiem
i cytatem. Materiał źródłowy jest oddzielony od wyjaśnienia modelu, które ma osobną etykietę.
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

Krótko: wybraliśmy je według spisanych reguł. To urzędy polskie i unijne oraz fact-checkerzy ze
statusem IFCN albo EFCSN. Lista jest jawna, ale to wciąż nasz wybór.

Szczegóły: wyszukiwarka zwraca tylko strony z domen na liście `ALLOWLIST`, a każda domena ma typ:
urzędowe, fact-checking, agencja prasowa albo baza narracji. Do korpusu przyjmujemy urzędy polskie i
unijne oraz fact-checkerów, których status sprawdziliśmy na stronie sieci (wpis ma datę odczytu).
Pravda jest zweryfikowanym członkiem EFCSN do 23.02.2028. Dowody od tego samego wydawcy, z tym samym
cytatem albo z tej samej agencji prasowej liczą się jako jedno źródło. EUvsDisinfo nigdy sam nie
rozstrzyga.

Słabe strony: lista to decyzja zespołu i nikt z zewnątrz nie badał jej różnorodności. Część
fact-checkingowa korpusu to 15 rekordów Pravdy. Demagoga bierzemy tylko przez Google Fact Check
(decyzja z 21.11).

Źródła: [prawdowid/websearch.py](../../prawdowid/websearch.py#L52),
[corpus/catalog.yaml](../../corpus/catalog.yaml), [docs/corpus.md](../corpus.md), [risks.md](risks.md).

### 5. Jak dodajecie i wykluczacie źródła?

Krótko: przez jeden plik z regułami, w którym każda decyzja ma powód i datę. Po każdej zmianie
puszczamy eval.

Szczegóły: [corpus/catalog.yaml](../../corpus/catalog.yaml) ma reguły przyjęcia, aktualizacji i
wykluczenia. Źródło wypada, gdy robots.txt go zabrania, gdy strona odrzuca skrypty, gdy jest
niedostępna dłużej niż jej okres odświeżania, gdy traci status fact-checkera albo gdy warunki
przestają pozwalać na fragment. Może też wypaść decyzją zespołu, jak Demagog 21.11. Wykluczone wpisy
zostają w katalogu z powodem i datą. Pojedynczy dokument usuwamy przez `removed_urls` i przebudowę
korpusu. Okres odświeżania wynosi od godziny (ostrzeżenia IMGW) do 30 dni (akty UE). Domenę w
wyszukiwarce dodajemy w kodzie i w [docs/sources.md](../sources.md) w jednym commicie, a test nie
przejdzie, gdy lista w dokumentacji się rozjedzie. Zmiany kodu nie wypchniemy bez czystego evalu na tym samym
commicie. Automatycznego odświeżania na serwerze jeszcze nie ma (#90).

Źródła: [docs/corpus.md](../corpus.md), [tests/test_websearch.py](../../tests/test_websearch.py),
[.githooks/pre-push](../../.githooks/pre-push), [#90](https://github.com/00200200/HackNation2026/issues/90).

### 6. Polscy fact-checkerzy blokują wasz serwer. Co wtedy?

Krótko: nie obchodzimy blokady. Bierzemy tylko to, co zwraca wyszukiwarka, i oznaczamy to jako
fragment z wyników.

Szczegóły: 22.11 około 00:50 z naszego serwera konkret24.tvn24.pl, sprawdzam.afp.com i
demagog.org.pl odpowiadały 403 przy każdym user agencie, a oko.press i pravda.org.pl odpowiadały
200 (#95, komentarz w #76). Brief zabrania obchodzenia zabezpieczeń, a nasze pobieranie nigdy nie
omija odpowiedzi 401, 403, 429 ani blokady botów. Dziś trafienie, którego strony nie da się pobrać,
po prostu wypada, choć wyszukiwarka zwróciła jego fragment (#95).

Zasadę na ten przypadek zatwierdził Michał 22.11.2026. Gdy nie możemy pobrać strony sami (blokada,
przekroczony czas, za duży plik, nieobsługiwany typ), dowodem staje się tytuł i fragment zwrócone
przez wyszukiwarkę. Odpowiedź oznacza go jako „fragment z wyników wyszukiwarki; strona nie pozwala
na pobranie”. Cytat sprawdzamy na tym fragmencie jak na każdym innym. Pełnej treści takiej strony nie
zapisujemy i nigdy nie pobieramy jej inną drogą. Stan: wdrożenie trwa w #95, na `main` go jeszcze
nie ma.

Źródła: [#95](https://github.com/00200200/HackNation2026/issues/95),
[#76](https://github.com/00200200/HackNation2026/issues/76), [docs/sources.md](../sources.md),
[prawdowid/safefetch.py](../../prawdowid/safefetch.py).

### 7. Co, jeśli źródło jest objęte sankcjami UE?

Krótko: status źródła nigdy nie decyduje o werdykcie. Planujemy osobną, neutralną notatkę, ale
jeszcze jej nie zbudowaliśmy.

Szczegóły: brief zabrania rozstrzygania prawdziwości na podstawie statusu źródła, także sankcji UE.
ADR 0001 proponuje notatkę z aktem prawnym i datą sprawdzenia, braną tylko z urzędowego źródła UE.
Notatka nie zmienia werdyktu ani jego siły (#81). Media objęte sankcjami nie mogą dziś być dowodem,
bo lista domen wyszukiwarki zawiera tylko urzędy, fact-checkerów i PAP.

Źródła: [ADR 0001](../adr/0001-evidence-retrieval-and-verdict.md), sekcje 5 i 6,
[prawdowid/websearch.py](../../prawdowid/websearch.py#L52),
[#81](https://github.com/00200200/HackNation2026/issues/81).

### 8. Co, jeśli tekst albo strona źródłowa zawiera polecenia dla modelu?

Krótko: traktujemy je jak dane. Nie wykonujemy ich, mówimy o tym użytkownikowi i zapisujemy
zdarzenie.

Szczegóły: instrukcje systemowe są oddzielone od danych. Dwa detektory: stałe wzorce w kodzie i
flaga od modelu, który wyodrębnia twierdzenia. Zdarzenie bezpieczeństwa zapisujemy bez treści ataku,
a strona pokazuje: „W treści są zwroty, które wyglądają na polecenia dla modelu. Nie wykonaliśmy ich
i sprawdziliśmy resztę”. Polecenie, które sędzia znajdzie w pobranej stronie, też trafia do
zdarzeń, z miejscem `source`.

Wyniki z [HISTORY.md](../../evals/results/HISTORY.md): odporność na injection 0,000 w szybkim
przebiegu na `95e6177` i 0,571 w pełnym przebiegu na `8c6f396` (ten przebieg jest zniekształcony),
przy progu 0,90. Wzorce pisaliśmy, znając pierwsze trzy przypadki E, więc potrzebujemy nowych.
Przypadki z poleceniem ukrytym w stronie jeszcze się nie uruchamiają (#94), a sprawdzanie pobranych
źródeł czeka w PR #72.

Źródła: [risks.md](risks.md), [prawdowid/verifier.py](../../prawdowid/verifier.py),
[frontend/public/app.js](../../frontend/public/app.js), [WORKLOG.md](../../WORKLOG.md) (wpis do #15),
[#94](https://github.com/00200200/HackNation2026/issues/94),
[PR #72](https://github.com/00200200/HackNation2026/pull/72).

### 9. Co się dzieje, gdy źródło nie działa albo skończy się limit?

Krótko: mówimy, co nie zadziałało. Awaria nigdy nie udaje werdyktu.

Szczegóły: każde źródło ma własny limit czasu. Google Fact Check ma 15 s, EUvsDisinfo 5 s w potoku,
jedno zapytanie do wyszukiwarki 10 s, pobranie strony 8 s, a całe sprawdzenie 25 s. Twierdzenie,
którego wszystkie źródła padły albo nie zdążyły, dostaje „nie sprawdzono” z powodem. Brak klucza do
modelu albo jego błąd daje komunikat techniczny. Jedenaste zapytanie w ciągu minuty dostaje
komunikat „Wysłano za dużo zapytań w krótkim czasie”. Eval ma 4 przypadki J. Dwa (FC-J01, FC-J02)
pomijamy, a dwa pozostałe (J01, J02) liczymy bez zasymulowanej awarii, bo przełącznika awarii
jeszcze nie ma (#60).

Znana luka: gdy jedno źródło padnie, a pozostałe nic nie znajdą, odpowiedź może brzmieć „brak
wystarczających dowodów” (#60). Gdy skończą się kredyty wyszukiwarki, twierdzenia wracają jako „nie
sprawdzono”. Czy komunikat mówi wtedy o limicie wyszukiwarki, sprawdza #75.

Źródła: [prawdowid/pipeline.py](../../prawdowid/pipeline.py),
[prawdowid/factcheck.py](../../prawdowid/factcheck.py), [prawdowid/app.py](../../prawdowid/app.py),
[README](../../README.md#configuration), [#60](https://github.com/00200200/HackNation2026/issues/60),
[#75](https://github.com/00200200/HackNation2026/issues/75).

### 10. Dlaczego tak często „nie udało mi się potwierdzić”?

Krótko: wolimy przyznać, że nie wiemy, niż zgadywać. Ale część tych odpowiedzi to nasz błąd w
pobieraniu stron i właśnie go naprawiamy.

Szczegóły: brief wymaga poprawnego wstrzymania się od oceny w co najmniej 80% przypadków bez
dowodów. W szybkich przebiegach mamy 1,000, w zniekształconym pełnym przebiegu na `8c6f396` 0,583
([HISTORY.md](../../evals/results/HISTORY.md)). Tylko że
w przebiegu na stagingu 22.11 wyszukiwarka znajdowała strony, a potem je odrzucała: 102, bo
robots.txt odpowiadał 403 (czytane jako zakaz wszystkiego), 36 bez tekstu, tytułu albo daty, 17 po
przekroczeniu 8 s, 8 większych niż 2 MB i 5 plików PDF (#95). Poprawki są w #95. Korpus urzędowy też
jeszcze nie jest podpięty (#74).

Źródła: [HISTORY.md](../../evals/results/HISTORY.md),
[#95](https://github.com/00200200/HackNation2026/issues/95),
[#74](https://github.com/00200200/HackNation2026/issues/74).

### 11. Jakie macie wyniki i czy utrzymacie je na zbiorze ukrytym?

Krótko: żaden zapisany przebieg nie spełnia wszystkich progów i tego nie ukrywamy. Każdy przebieg
jest w repozytorium razem z commitem.

Szczegóły: nasz zestaw to 73 przypadki, 41 w zestawie A-J i 32 w zestawie FC. Rozkład scenariuszy:
A 23, B 10, C 6, D 8, E 7, G 6, H 2, I 7, J 4. Etykiety pochodzą z ocen Demagoga, Konkret24,
EUvsDisinfo i stron urzędowych, a przy każdym przypadku zapisaliśmy, skąd jest etykieta. Wyjątek to
przypadki D01-D04 oraz H01 i H02: plotki wymyślone przez zespół, o których nikt nie pisał, więc
poprawna odpowiedź to brak dowodów. Zapisane przebiegi: szybki na `95e6177` dał macro-F1 0,100, abstencję
1,000 i odporność na injection 0,000. Pełny na `8c6f396` (71 przypadków) dał macro-F1 0,498,
abstencję 0,583, odporność na injection 0,571 i medianę 18,2 s. Ten wiersz odtworzyliśmy bez pliku
JSON, a sam przebieg zniekształciły timeouty Anthropic i zbyt ciasny budżet 25 s. Przebieg na
commicie zgłoszenia: [z #16].

Zbioru ukrytego nie znamy. Zasada: żadnych przypadków ani odpowiedzi z evalu w promptach i w kodzie.
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

Źródła: [prawdowid/privacy.py](../../prawdowid/privacy.py#L20), [docs/privacy.md](../privacy.md),
[risks.md](risks.md), [frontend/public/index.html](../../frontend/public/index.html),
[#82](https://github.com/00200200/HackNation2026/issues/82),
[#85](https://github.com/00200200/HackNation2026/issues/85).

### 13. Ile to kosztuje?

Krótko: obywatel płaci zero. Nas jedno sprawdzenie kosztuje według dzisiejszych pomiarów od 31 do 37
groszy, a serwer z domeną około 43 zł miesięcznie.

Szczegóły: modele to 0,0525 USD za sprawdzenie (jeden przebieg pełnego potoku na 8 przypadkach,
wpis z 21.11 w WORKLOG). Tavily dokłada około 4,9 kredytu po 0,005 do 0,008 USD. Na 1000 sprawdzeń
wychodzi od 77 do 92 USD, czyli od 312 do 372 zł. Koszty stałe: VPS-2 od 37,85 zł brutto miesięcznie,
domena 58,99 zł rocznie przy odnowieniu, bot Discord 0 zł ponad serwer. Koszt 100 testów w
HISTORY.md to 1,82 USD, ale z wersji sprzed Tavily i sędziego. Ostateczne liczby policzymy z pełnego
przebiegu (#16).

Źródła: [cost.md](cost.md), [HISTORY.md](../../evals/results/HISTORY.md), [WORKLOG.md](../../WORKLOG.md).

### 14. Co przy 10 i 100 razy większym ruchu?

Krótko: koszt rośnie liniowo, a rachunek to prawie wyłącznie tokeny modeli i kredyty wyszukiwarki.
Serwer to poniżej 2%. Przepustowości jednego serwera jeszcze nie zmierzyliśmy.

Szczegóły: przy umownych 10 000 sprawdzeń miesięcznie wychodzi około 3726 zł, przy 100 000 około
37 171 zł plus kolejne serwery. Modele to od 57 do 63% kosztów zmiennych. Największa dźwignia to
model do wyodrębniania twierdzeń: dziś Opus 5.5, a token Sonnet 5.5 kosztuje połowę tego. Zamianę
zrobimy dopiero po pomiarze jakości (#88). Dziś backend to jeden proces z limitem zapytań w pamięci,
na jednym serwerze bez zapasowego. Test obciążeniowy to #88.

Źródła: [cost.md](cost.md), [Dockerfile](../../Dockerfile), [docs/deploy.md](../deploy.md),
[#88](https://github.com/00200200/HackNation2026/issues/88).

### 15. Czy nie uzależniacie MSZ od jednego dostawcy? Gdzie są przetwarzane dane?

Krótko: model zmienia się jedną zmienną środowiskową, a wyszukiwarkę jedną funkcją. Serwer stoi w
Niemczech. Dostawcy modeli i wyszukiwarki są spoza EOG i mówimy to wprost.

Szczegóły: modele wybieramy przez PydanticAI zmiennymi `PRAWDOWID_MODEL`, `PRAWDOWID_RERANK_MODEL` i
`PRAWDOWID_JUDGE_MODEL`, bez przebudowy obrazu. Wyszukiwarka siedzi za kontraktem `SearchProvider`,
a zamienniki (Exa, Brave) porównaliśmy przy wyborze dostawcy (decyzja do #7 w WORKLOG). Embeddingi liczy lokalny
model e5-large (licencja MIT), baza to PostgreSQL z pgvector. Serwer: OVHcloud, Limburg, Niemcy.

Czego jeszcze nie ma: nie pokazaliśmy działania na modelu przetwarzanym w UE. Gdzie przetwarzają
dane Anthropic, Google, Tavily i EUvsDisinfo, jest UNCONFIRMED. Ani Tavily, ani Exa, ani Brave nie
opisuje przetwarzania w EOG (#85).

Źródła: [prawdowid/verifier.py](../../prawdowid/verifier.py#L43),
[prawdowid/rerank.py](../../prawdowid/rerank.py#L49), [prawdowid/judge.py](../../prawdowid/judge.py#L62),
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

Krótko: dziś człowiekiem jest czytelnik, który dostaje źródła i ocenia sam. Kolejki eksperta jeszcze
nie ma, a w pilotażu to ona zatwierdzi publikacje.

Szczegóły: brief chce, żeby przy sprawach wysokiego ryzyka i powtarzających się pytaniach bez źródeł
system powiadamiał osobę wskazaną przez administratora. Spraw moderatora nie zbudowaliśmy (#79).
Odpowiedź nigdy nie mówi więc, że coś przekazaliśmy moderatorowi. Eval ma dwa przypadki H, a
`moderator_loop` wynosi 0,0 w [evals/results/latest.json](../../evals/results/latest.json) i w pełnym
przebiegu opisanym w [docs/eval-notes.md](../eval-notes.md). Plan na pilotaż: sprawy dla
powtarzających się pytań bez odpowiedzi, widok administratora za tokenem i zatwierdzanie publikacji
ze śladem decyzji.

Źródła: [#79](https://github.com/00200200/HackNation2026/issues/79), [pilot.md](pilot.md),
[evals/cases.jsonl](../../evals/cases.jsonl).

### 19. Czy obsługujecie zrzuty ekranu i zdjęcia?

Krótko: nie. Scenariusz F zostawiliśmy na później (#80) i nie udajemy, że go mamy.

Szczegóły: brief zabrania deklarowania wyszukiwania odwrotnego obrazu bez działającego API albo
jasno ograniczonej lokalnej bazy. Nie przechowujemy obrazów, dźwięku ani wideo. Link do pliku, który
nie jest stroną HTML ani PDF-em, dostaje prośbę o wklejenie tekstu. Plan w #80: odczytać tekst i datę
z obrazu, a potem sprawdzać tą samą drogą co tekst.

Źródła: [docs/corpus.md](../corpus.md), [prawdowid/link.py](../../prawdowid/link.py),
[#80](https://github.com/00200200/HackNation2026/issues/80).

### 20. Czy możemy to uruchomić sami?

Krótko: tak. `make up` stawia całość w Dockerze, a eval odtwarza nasze liczby jednym poleceniem.

Szczegóły: klucze wpisuje się do ignorowanego pliku `.env`. Wymagany jest tylko `ANTHROPIC_API_KEY`.
Bez kluczy do Google Fact Check, Tavily i EUvsDisinfo te źródła są zgłaszane jako niedostępne. Bez
klucza do modelu strona się otwiera, ale każde sprawdzenie kończy się komunikatem technicznym. Samo
API: `make dev`. Eval: `PRAWDOWID_URL=http://127.0.0.1:8000 uv run python -m evals.run --quick`.
Wdrożenie produkcyjne opisuje [docs/deploy.md](../deploy.md). Dokumentacja API pod `/docs` działa
lokalnie, ale na publicznym demo zwraca 404 (#87). Publiczna wersja: https://faktczyfejk.pl.

Źródła: [README](../../README.md#run), [docs/deploy.md](../deploy.md),
[.claude/skills/prawdowid-eval/SKILL.md](../../.claude/skills/prawdowid-eval/SKILL.md),
[#87](https://github.com/00200200/HackNation2026/issues/87).
