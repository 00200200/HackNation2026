# Konspekt prezentacji

Talia slajdów: [docs/pitch/slides.html](../pitch/slides.html) (źródło),
[PDF](../pitch/faktczyfejk-pitch.pdf) i [PPTX](../pitch/faktczyfejk-pitch.pptx), 12 slajdów przy
limicie 12 ([issue #18](https://github.com/00200200/HackNation2026/issues/18)). Wcześniejszy
konspekt w tym pliku opisywał szkic z wynikami testu na commicie 95e6177; talia go zastąpiła.
Poniżej: co mówi każdy slajd i skąd to wiadomo.

| Slajd | Treść | Podstawa |
|---|---|---|
| 1 | Tytuł, zespół, hasło „Sprawdź, zanim podasz dalej.” | — |
| 2 | Problem: fałszywa wiadomość idzie dalej, zanim ktoś ją sprawdzi | zadanie MSZ |
| 3 | Dla kogo: obywatel, także o niskich kompetencjach cyfrowych, oraz analityk lub moderator MSZ (dziennik sprawdzeń, kolejka moderatora); badań z użytkownikami nie prowadziliśmy | zadanie MSZ, punkt 3; dziennik sprawdzeń i sprawy moderatora w [privacy.md](../privacy.md), #79 |
| 4 | Format odpowiedzi: pytanie z przykładów organizatora i wzór odpowiedzi w ich formacie, nie zapis odpowiedzi produktu | przykłady w `frontend/public/index.html`, format z commita b8ce6f9 |
| 5 | Pięć ocen; „nie sprawdzono”, błąd techniczny, strona nie do sprawdzenia i prośba o doprecyzowanie osobno | [contract.py](../../prawdowid/contract.py), [pipeline.py](../../prawdowid/pipeline.py) |
| 6 | Przepływ: tekst albo link, twierdzenia, źródła równolegle, cytat sprawdzany w kodzie, werdykt z reguł | [architecture.md](architecture.md), [ADR 0001](../adr/0001-evidence-retrieval-and-verdict.md) |
| 7 | Sześć ryzyk z zadania: zabezpieczenie i to, co zostaje | [risks.md](risks.md) |
| 8 | Kanały: WWW działa; adapter demonstracyjny `/czat` działa na faktczyfejk.pl (`c422f2d`, 22.11 o 09:08 odpowiadał 200) i podpisuje ocenę fact-checkera i fragment z wyszukiwarki; kod bota Discord gotowy, wdrożenie czeka; zrzut strony głównej z faktczyfejk.pl (22.11, `c422f2d`) | [deploy.md](../deploy.md), sekcja 7; `frontend/public/czat.js` (`sourceItem`, #116, podpisy od `5f7304d`) i `tests/test_czat.py`; [WORKLOG](../../WORKLOG.md) |
| 9 | Nasz zestaw, progi jury: pełny przebieg, 75 przypadków, commit `c422f2d` (`main` po #129 i #134, staging na VPS zbudowany z tego commita, wyszukiwanie na Tavily jak na produkcji): macro-F1 0,92 (62 z 69 przypadków z etykietą oceny trafionych; 42 etykiety z ocen Demagoga; sześć wcześniejszych pełnych przebiegów rundy 4 od 0,81 do 0,92), mediana 14,6 s (plik nie zapisuje, czy pamięć wyszukiwań była pusta; 15,1 s z pustą pamięcią na `af7ec13`), abstencja 1,00 (12 z 12), koszt modeli 34,60 USD za 1000 (3,46 USD za 100); poprawność cytatów tylko jako dosłowna obecność cytatu z korpusu, 3 z 7 przypadków wstrzyknięć znane wzorcom, zgodność kanałów z pamięci podręcznej, odporność na wstrzyknięcia 1,00, ale właściwą ocenę ma 6 z 7 takich przypadków (0,857), end-to-end 0,99 (tylko J01), pętla moderatora 1,00; 11 przypadków z poleceniem na stronie ten przebieg pominął, a osobne przebiegi na `5e5be00` (ten sam kod produktu) dały na nich 11/11 poprawnych werdyktów i odporność 1,00 | [history/20261122T071235.638303Z-c422f2d-full.json](../../evals/results/history/20261122T071235.638303Z-c422f2d-full.json) i [HISTORY.md](../../evals/results/HISTORY.md); zastrzeżenia: [eval-notes.md](../eval-notes.md), [architecture.md](architecture.md#saved-test-results-and-reproduction) |
| 10 | Wdrożenie: serwer w Niemczech, co trafia poza EOG, a kto nie podaje miejsca przetwarzania (Google, EUvsDisinfo, gov.pl), model w zmiennej środowiskowej, korpus 1158 dokumentów, oceny fact-checkerów z Google Fact Check Tools i ze stron recenzji (#127), lista źródeł `/zrodla` | [deploy.md](../deploy.md), [corpus.md](../corpus.md), `frontend/public/zrodla.html` (#83), tabela dostawców w `docs/privacy.md` (z [PR #124](https://github.com/00200200/HackNation2026/pull/124), w `integration/r4`) |
| 11 | Co dalej: pętla moderatora (działa na faktczyfejk.pl, #79, token ustawiony: `GET /api/cases` bez tokenu zwraca 401; potem ekran spraw i zatwierdzanie odpowiedzi), trafniejsze oceny (w przebiegu na `c422f2d` 4 z 7 pomyłek w ocenach to „brak wystarczających dowodów” tam, gdzie oczekiwaliśmy oceny), baza incydentów MSZ | plan, nie stan; pomyłki z pełnego przebiegu na `c422f2d` ([eval-notes.md](../eval-notes.md)) |
| 12 | Podziękowanie, kod QR do https://faktczyfejk.pl, link do repozytorium | repozytorium było prywatne 22.11.2026: przed wysłaniem zob. punkt #18 w „Next” w [WORKLOG](../../WORKLOG.md) |

Koszt 1000 sprawdzeń i założenia: [cost.md](cost.md). Plan pilotażu dla MSZ: [pilot.md](pilot.md); tekst do filmu: [pitch.md](pitch.md); pytania i odpowiedzi: [qa.md](qa.md). Film nie jest częścią tego pliku.
