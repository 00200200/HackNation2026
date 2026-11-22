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
| 8 | Kanały: WWW działa, bot Discord nieuruchomiony, adapter w przygotowaniu; zrzut strony głównej z kodu `integration/r2` | [deploy.md](../deploy.md), sekcja 7; [WORKLOG](../../WORKLOG.md) |
| 9 | Szybki test na 10 przypadkach, commit edd34a5, ekstrakcja Claude Opus; przy abstencji, wstrzyknięciach i zgodności kanałów liczba przypadków | [latest.json](../../evals/results/latest.json), [architecture.md](architecture.md#saved-test-results-and-reproduction) |
| 10 | Wdrożenie: serwer w Niemczech, co trafia poza EOG, model w zmiennej środowiskowej, korpus 1158 dokumentów | [deploy.md](../deploy.md), [corpus.md](../corpus.md), tabela dostawców w `docs/privacy.md` z [PR #124](https://github.com/00200200/HackNation2026/pull/124) (jeszcze nie scalony) |
| 11 | Co dalej: trafniejsze oceny, baza incydentów MSZ, panel analityka | plan, nie stan |
| 12 | Podziękowanie, kod QR do https://faktczyfejk.pl, link do repozytorium | repozytorium było prywatne 22.11.2026: przed wysłaniem zob. [description.md](description.md) |

Koszt 1000 sprawdzeń i założenia: [cost.md](cost.md). Film nie jest częścią tego pliku.
