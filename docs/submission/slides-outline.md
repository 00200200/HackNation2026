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
| 3 | Dla kogo: obywatel, także o niskich kompetencjach cyfrowych, oraz analityk lub moderator MSZ; badań z użytkownikami nie prowadziliśmy | zadanie MSZ, punkt 3; dziennik sprawdzeń w [privacy.md](../privacy.md) |
| 4 | Format odpowiedzi: pytanie z przykładów organizatora i wzór odpowiedzi w ich formacie, nie zapis odpowiedzi produktu | przykłady w `frontend/public/index.html`, format z commita b8ce6f9 |
| 5 | Pięć ocen; „nie sprawdzono”, błąd techniczny, strona nie do sprawdzenia i prośba o doprecyzowanie osobno | [contract.py](../../prawdowid/contract.py), [pipeline.py](../../prawdowid/pipeline.py) |
| 6 | Przepływ: tekst albo link, twierdzenia, źródła równolegle, cytat sprawdzany w kodzie, werdykt z reguł | [architecture.md](architecture.md), [ADR 0001](../adr/0001-evidence-retrieval-and-verdict.md) |
| 7 | Sześć ryzyk z zadania: zabezpieczenie i to, co zostaje | [risks.md](risks.md) |
| 8 | Kanały: WWW działa; adapter demonstracyjny `/czat` czeka na wdrożenie (22.11 o 04:30 zwracał 404 na faktczyfejk.pl) i pokazuje ocenę fact-checkera i fragment z wyszukiwarki jeszcze bez podpisu; kod bota Discord gotowy, wdrożenie czeka; zrzut strony głównej z kodu `integration/r2` | [deploy.md](../deploy.md), sekcja 7; `frontend/public/czat.js` (`sourceItem`, #116) wobec `frontend/public/app.js` (`sourceText`); [WORKLOG](../../WORKLOG.md) |
| 9 | Nasz zestaw, progi jury: pełny przebieg, 75 przypadków, commit ca48b84; przy macro-F1 42 etykiety z ocen Demagoga, poprawność cytatów tylko jako dosłowna obecność cytatu z korpusu, 3 z 7 przypadków wstrzyknięć znane wzorcom, zgodność kanałów z pamięci podręcznej; 11 przypadków z poleceniem na stronie pominiętych | [history/20261122T021757.182695Z-ca48b84-full.json](../../evals/results/history/20261122T021757.182695Z-ca48b84-full.json) i [HISTORY.md](../../evals/results/HISTORY.md); zastrzeżenia: [eval-notes.md](../eval-notes.md), [architecture.md](architecture.md#saved-test-results-and-reproduction) |
| 10 | Wdrożenie: serwer w Niemczech, co trafia poza EOG, a kto nie podaje miejsca przetwarzania (Google, EUvsDisinfo, gov.pl), model w zmiennej środowiskowej, korpus 1158 dokumentów, lista źródeł `/zrodla` | [deploy.md](../deploy.md), [corpus.md](../corpus.md), `frontend/public/zrodla.html` (#83), tabela dostawców w `docs/privacy.md` z [PR #124](https://github.com/00200200/HackNation2026/pull/124) (jeszcze nie scalony) |
| 11 | Co dalej: pętla moderatora (w budowie), trafniejsze oceny (najczęstsza pomyłka testu: „wprowadzające w błąd” zamiast „fałszywe”), baza incydentów MSZ | plan, nie stan; pomyłki z pełnego przebiegu |
| 12 | Podziękowanie, kod QR do https://faktczyfejk.pl, link do repozytorium | repozytorium było prywatne 22.11.2026: przed wysłaniem zob. punkt #18 w „Next” w [WORKLOG](../../WORKLOG.md) |

Koszt 1000 sprawdzeń i założenia: [cost.md](cost.md). Film nie jest częścią tego pliku.
